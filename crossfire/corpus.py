"""Real-world corpus loading and evaluation."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from crossfire.errors import CrossfireError, LoadError
from crossfire.models import Rule

DRIFT_THRESHOLD = 0.05

log = logging.getLogger("crossfire.corpus")


@dataclass
class LabeledEntry:
    """A corpus entry with an optional ground-truth label."""

    text: str
    label: str = ""  # expected rule name / category
    source: str = ""  # origin identifier


@dataclass
class RuleMetrics:
    """Precision/recall/F1 metrics for a single rule."""

    name: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    matched_count: int = 0  # total corpus entries this rule matched


@dataclass
class EvaluationReport:
    """Results of evaluating rules against a real-world corpus."""

    total_entries: int
    labeled_entries: int
    unlabeled_entries: int
    rules_evaluated: int
    rule_metrics: list[RuleMetrics]
    match_matrix: dict[str, int]  # rule_name → match_count
    co_firing: list[tuple[str, str, int]]  # (rule_a, rule_b, co_fire_count)
    duration_s: float
    summary: dict[str, object]


@dataclass
class DiffRuleResult:
    """Per-rule comparison across two corpora."""

    rule: str
    matches_a: int
    matches_b: int
    rate_a: float
    rate_b: float
    drift: float
    significant: bool


@dataclass
class DiffReport:
    """Results of comparing rule behavior across two corpora."""

    name_a: str
    name_b: str
    entries_a: int
    entries_b: int
    rules_with_matches: int
    rules_with_drift: int
    results: list[DiffRuleResult]


def load_corpus_jsonl(
    path: str | Path,
    *,
    text_field: str = "text",
    label_field: str = "label",
    source_field: str = "source",
) -> list[LabeledEntry]:
    """Load corpus from a JSONL file.

    Each line is a JSON object with at least a text field.

    Args:
        path: Path to JSONL file.
        text_field: Field name for the text content.
        label_field: Field name for the ground-truth label.
        source_field: Field name for the origin identifier.

    Returns:
        List of LabeledEntry objects.
    """
    path = Path(path)
    if not path.exists():
        raise LoadError(f"Corpus file not found: {path}")

    entries: list[LabeledEntry] = []
    errors = 0

    with open(path) as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                log.warning("Corpus line %d: invalid JSON: %s", line_num, e)
                errors += 1
                continue

            if not isinstance(obj, dict):
                log.warning("Corpus line %d: expected object, got %s", line_num, type(obj).__name__)
                errors += 1
                continue

            text = obj.get(text_field)
            if not text:
                log.debug(
                    "Corpus line %d: missing or empty '%s' field, skipping",
                    line_num,
                    text_field,
                )
                continue

            entries.append(
                LabeledEntry(
                    text=str(text),
                    label=str(obj.get(label_field, "")),
                    source=str(obj.get(source_field, "")),
                )
            )

    log.info("Loaded %d corpus entries from %s (%d errors)", len(entries), path, errors)
    if not entries:
        raise LoadError(f"No valid entries in corpus file: {path}")

    return entries


def load_corpus_git(
    repo_path: str | Path,
    *,
    max_commits: int = 500,
    max_line_length: int = 500,
) -> list[LabeledEntry]:
    """Load corpus from git diff history.

    Extracts added/modified lines from recent commits as corpus entries.
    Only text content — binary files are skipped.

    Args:
        repo_path: Path to the git repository.
        max_commits: Maximum number of commits to scan.
        max_line_length: Skip lines longer than this (likely binary/generated).

    Returns:
        List of LabeledEntry objects (unlabeled — label is empty).
    """
    repo_path = Path(repo_path)
    if not (repo_path / ".git").exists():
        raise LoadError(f"Not a git repository: {repo_path}")

    log.info("Extracting corpus from git history: %s (max %d commits)", repo_path, max_commits)
    t0 = time.monotonic()

    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"--max-count={max_commits}",
                "--diff-filter=AM",
                "-p",
                "--no-color",
                "--unified=0",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as err:
        raise CrossfireError(f"Git log timed out after 120s for {repo_path}") from err
    except FileNotFoundError as err:
        raise CrossfireError("git command not found — is git installed?") from err

    if result.returncode != 0:
        raise CrossfireError(f"git log failed: {result.stderr[:200]}")

    entries: list[LabeledEntry] = []
    current_commit = ""
    current_file = ""
    seen_lines: set[str] = set()

    for line in result.stdout.splitlines():
        if line.startswith("commit "):
            current_commit = line[7:14]  # short hash
        elif line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            content = line[1:]  # strip the leading +
            if not content.strip():
                continue
            if len(content) > max_line_length:
                continue
            if content in seen_lines:
                continue
            seen_lines.add(content)
            entries.append(
                LabeledEntry(
                    text=content,
                    label="",
                    source=f"{current_commit}:{current_file}",
                )
            )

    duration = time.monotonic() - t0
    log.info(
        "Extracted %d unique lines from %s in %.1fs",
        len(entries),
        repo_path,
        duration,
    )

    if not entries:
        raise LoadError(f"No content extracted from git history: {repo_path}")

    return entries


def evaluate_corpus(
    rules: list[Rule],
    corpus: list[LabeledEntry],
    *,
    redact_samples: bool = False,
) -> EvaluationReport:
    """Evaluate rules against a real-world corpus.

    For each corpus entry, check which rules match. Compute:
    - Per-rule match counts
    - Co-firing pairs (rules that fire on the same entry)
    - If labels present: precision, recall, F1 per rule

    Args:
        rules: List of rules to evaluate.
        corpus: List of corpus entries.
        redact_samples: If True, don't log matched text content.

    Returns:
        EvaluationReport with metrics and co-firing data.
    """
    t0 = time.monotonic()
    log.info("Evaluating %d rules against %d corpus entries", len(rules), len(corpus))

    # Per-rule match tracking
    match_counts: dict[str, int] = {r.name: 0 for r in rules}

    # Co-firing tracking: for each entry, which rules fire?
    co_fire_counts: dict[tuple[str, str], int] = {}

    # Labeled evaluation
    labeled = sum(1 for e in corpus if e.label)
    has_labels = labeled > 0
    tp: dict[str, int] = {r.name: 0 for r in rules}
    fp: dict[str, int] = {r.name: 0 for r in rules}
    fn: dict[str, int] = {r.name: 0 for r in rules}

    for entry_idx, entry in enumerate(corpus):
        firing_rules: list[str] = []
        firing_set: set[str] = set()
        for rule in rules:
            if rule.compiled.search(entry.text):
                firing_rules.append(rule.name)
                firing_set.add(rule.name)
                match_counts[rule.name] += 1

                if not redact_samples:
                    log.debug(
                        "Rule '%s' matched entry %d (source: %s)",
                        rule.name,
                        entry_idx,
                        entry.source,
                    )

        # Track co-firing pairs
        for i, name_a in enumerate(firing_rules):
            for name_b in firing_rules[i + 1 :]:
                key = (min(name_a, name_b), max(name_a, name_b))
                co_fire_counts[key] = co_fire_counts.get(key, 0) + 1

        # Labeled evaluation: check if the right rule(s) fired
        if has_labels and entry.label:
            label = entry.label
            for rule in rules:
                if rule.name == label or label in rule.tags:
                    if rule.name in firing_set:
                        tp[rule.name] += 1
                    else:
                        fn[rule.name] += 1
                else:
                    if rule.name in firing_set:
                        fp[rule.name] += 1

        # Progress every 10%
        if (entry_idx + 1) % max(1, len(corpus) // 10) == 0:
            pct = int((entry_idx + 1) / len(corpus) * 100)
            log.info("Evaluation progress: %d%%", pct)

    # Compute metrics per rule
    rule_metrics: list[RuleMetrics] = []
    for rule in rules:
        m = RuleMetrics(
            name=rule.name,
            matched_count=match_counts[rule.name],
        )
        if has_labels:
            m.true_positives = tp[rule.name]
            m.false_positives = fp[rule.name]
            m.false_negatives = fn[rule.name]
            total_predicted = m.true_positives + m.false_positives
            total_actual = m.true_positives + m.false_negatives
            m.precision = m.true_positives / total_predicted if total_predicted > 0 else 0.0
            m.recall = m.true_positives / total_actual if total_actual > 0 else 0.0
            if m.precision + m.recall > 0:
                m.f1 = 2 * m.precision * m.recall / (m.precision + m.recall)
            m.precision = round(m.precision, 4)
            m.recall = round(m.recall, 4)
            m.f1 = round(m.f1, 4)
        rule_metrics.append(m)

    # Sort co-firing by count descending
    co_firing = sorted(
        [(a, b, count) for (a, b), count in co_fire_counts.items()],
        key=lambda x: x[2],
        reverse=True,
    )

    duration = time.monotonic() - t0

    # Summary stats
    firing_rules_count = sum(1 for c in match_counts.values() if c > 0)
    avg_precision = 0.0
    avg_recall = 0.0
    if has_labels:
        active_metrics = [m for m in rule_metrics if m.true_positives + m.false_negatives > 0]
        if active_metrics:
            avg_precision = round(sum(m.precision for m in active_metrics) / len(active_metrics), 4)
            avg_recall = round(sum(m.recall for m in active_metrics) / len(active_metrics), 4)

    report = EvaluationReport(
        total_entries=len(corpus),
        labeled_entries=labeled,
        unlabeled_entries=len(corpus) - labeled,
        rules_evaluated=len(rules),
        rule_metrics=rule_metrics,
        match_matrix=match_counts,
        co_firing=co_firing[:100],  # top 100 co-firing pairs
        duration_s=round(duration, 1),
        summary={
            "rules_firing": firing_rules_count,
            "co_firing_pairs": len(co_firing),
            "avg_precision": avg_precision,
            "avg_recall": avg_recall,
        },
    )

    log.info(
        "Evaluation complete in %.1fs: %d rules fired, %d co-firing pairs",
        duration,
        firing_rules_count,
        len(co_firing),
    )
    if has_labels:
        log.info(
            "Labeled evaluation: avg precision=%.2f, avg recall=%.2f",
            avg_precision,
            avg_recall,
        )

    return report


def diff_corpora(
    rules: list[Rule],
    corpus_a: list[LabeledEntry],
    corpus_b: list[LabeledEntry],
    *,
    name_a: str = "corpus_a",
    name_b: str = "corpus_b",
    drift_threshold: float = DRIFT_THRESHOLD,
) -> DiffReport:
    """Compare rule behavior across two corpora.

    For each rule, compute match rate in each corpus and flag rules with
    significant divergence (coverage drift).

    Reuses evaluate_corpus() internally to avoid redundant O(R*C) scans.

    Args:
        rules: List of rules to evaluate.
        corpus_a: First corpus.
        corpus_b: Second corpus.
        name_a: Display name for first corpus.
        name_b: Display name for second corpus.
        drift_threshold: Minimum rate difference to flag as significant.

    Returns:
        DiffReport with per-rule divergence analysis.
    """
    log.info(
        "Differential analysis: %d rules against %s (%d entries) vs %s (%d entries)",
        len(rules),
        name_a,
        len(corpus_a),
        name_b,
        len(corpus_b),
    )

    report_a = evaluate_corpus(rules, corpus_a)
    report_b = evaluate_corpus(rules, corpus_b)

    results: list[DiffRuleResult] = []

    for rule in rules:
        matches_a = report_a.match_matrix.get(rule.name, 0)
        matches_b = report_b.match_matrix.get(rule.name, 0)

        rate_a = matches_a / len(corpus_a) if corpus_a else 0.0
        rate_b = matches_b / len(corpus_b) if corpus_b else 0.0
        drift = abs(rate_a - rate_b)

        if matches_a > 0 or matches_b > 0:
            results.append(
                DiffRuleResult(
                    rule=rule.name,
                    matches_a=matches_a,
                    matches_b=matches_b,
                    rate_a=round(rate_a, 4),
                    rate_b=round(rate_b, 4),
                    drift=round(drift, 4),
                    significant=drift > drift_threshold,
                )
            )

    results.sort(key=lambda r: r.drift, reverse=True)

    significant = [r for r in results if r.significant]
    log.info(
        "Differential analysis complete: %d rules with matches, %d with significant drift",
        len(results),
        len(significant),
    )

    return DiffReport(
        name_a=name_a,
        name_b=name_b,
        entries_a=len(corpus_a),
        entries_b=len(corpus_b),
        rules_with_matches=len(results),
        rules_with_drift=len(significant),
        results=results,
    )
