"""Per-rule quality scoring and broad pattern detection."""

from __future__ import annotations

import logging
import random
import re
import string
try:
    import re._parser as sre_parse  # Python 3.13+
except ImportError:
    import sre_parse  # type: ignore[no-redef]  # Python < 3.13
from dataclasses import dataclass, field
from typing import Optional

from crossfire.evaluator import MatchMatrix
from crossfire.models import CorpusEntry, Rule

log = logging.getLogger("crossfire.quality")


@dataclass
class RuleQuality:
    """Quality metrics for a single rule."""

    name: str
    source: str
    specificity: float  # 0.0 = matches everything, 1.0 = very selective
    false_positive_potential: int  # number of OTHER rules' corpus strings this rule matches
    pattern_complexity: int  # regex AST node count
    unique_coverage: int  # corpus strings matched by this rule and NO other rule
    is_broad: bool  # appears in >N overlap pairs
    overlap_count: int  # number of rules this overlaps with
    flags: list[str] = field(default_factory=list)  # human-readable quality warnings


@dataclass
class QualityReport:
    """Quality assessment for all rules."""

    rules: list[RuleQuality]
    broad_patterns: list[RuleQuality]  # rules flagged as umbrella patterns
    low_specificity: list[RuleQuality]  # rules matching >90% of random strings
    fully_redundant: list[RuleQuality]  # rules with unique_coverage == 0
    summary: dict[str, object]


def assess_quality(
    rules: list[Rule],
    corpus: list[CorpusEntry],
    matrix: MatchMatrix,
    corpus_sizes: dict[str, int],
    *,
    broad_threshold: int = 5,
    specificity_samples: int = 200,
    seed: Optional[int] = None,
) -> QualityReport:
    """Assess quality of all rules.

    Args:
        rules: List of rules to assess.
        corpus: Generated corpus entries.
        matrix: Match matrix from evaluator.
        corpus_sizes: Corpus size per rule.
        broad_threshold: Number of overlap pairs to flag as "broad pattern".
        specificity_samples: Random strings to test for specificity.
        seed: Random seed for specificity testing.

    Returns:
        QualityReport with per-rule metrics and aggregate findings.
    """
    rng = random.Random(seed) if seed is not None else random.Random()

    log.info("Quality assessment started for %d rules", len(rules))

    overlap_counts = _compute_overlap_counts(matrix, rules)
    unique_coverage = _compute_unique_coverage(matrix, corpus_sizes, rules)
    random_corpus = _generate_random_strings(specificity_samples, rng)

    # Batch specificity: one pass over random corpus for all rules
    random_match_counts: dict[str, int] = {r.name: 0 for r in rules}
    for s in random_corpus:
        for rule in rules:
            if rule.compiled.search(s):
                random_match_counts[rule.name] += 1

    results: list[RuleQuality] = []
    for rule in rules:
        quality = _assess_single_rule(
            rule, matrix, corpus_sizes, overlap_counts,
            unique_coverage, random_match_counts,
            len(random_corpus), broad_threshold,
        )
        results.append(quality)

    broad_patterns = [r for r in results if r.is_broad]
    low_spec = [r for r in results if r.specificity < 0.1]
    redundant = [r for r in results if r.unique_coverage == 0
                 and corpus_sizes.get(r.name, 0) > 0]

    if broad_patterns:
        log.info(
            "%d broad patterns detected (>%d overlap pairs each)",
            len(broad_patterns), broad_threshold,
        )
        for bp in broad_patterns:
            log.info(
                "  Broad pattern: '%s' overlaps with %d rules",
                bp.name, bp.overlap_count,
            )

    if low_spec:
        log.warning(
            "%d rules have low specificity (match >90%% of random strings): %s",
            len(low_spec),
            ", ".join(r.name for r in low_spec[:5]) + ("..." if len(low_spec) > 5 else ""),
        )

    if redundant:
        log.info(
            "%d rules have zero unique coverage (fully redundant)",
            len(redundant),
        )

    report = QualityReport(
        rules=results,
        broad_patterns=broad_patterns,
        low_specificity=low_spec,
        fully_redundant=redundant,
        summary={
            "total_rules": len(results),
            "broad_patterns": len(broad_patterns),
            "low_specificity": len(low_spec),
            "fully_redundant": len(redundant),
            "avg_specificity": round(
                sum(r.specificity for r in results) / len(results), 3
            ) if results else 0,
            "avg_complexity": round(
                sum(r.pattern_complexity for r in results) / len(results), 1
            ) if results else 0,
        },
    )

    log.info(
        "Quality assessment complete: %d broad, %d low-specificity, %d redundant",
        len(broad_patterns), len(low_spec), len(redundant),
    )

    return report


def _assess_single_rule(
    rule: Rule,
    matrix: MatchMatrix,
    corpus_sizes: dict[str, int],
    overlap_counts: dict[str, int],
    unique_coverage: dict[str, int],
    random_match_counts: dict[str, int],
    random_corpus_size: int,
    broad_threshold: int,
) -> RuleQuality:
    """Assess quality metrics for a single rule."""
    random_matches = random_match_counts.get(rule.name, 0)
    specificity = 1.0 - (random_matches / random_corpus_size) if random_corpus_size else 1.0

    fp_potential = 0
    rule_matches = matrix.get(rule.name, {})
    for other_rule, count in rule_matches.items():
        if other_rule != rule.name and count > 0:
            fp_potential += count

    complexity = _pattern_complexity(rule.pattern)
    ovr_count = overlap_counts.get(rule.name, 0)
    unique = unique_coverage.get(rule.name, 0)
    actual = corpus_sizes.get(rule.name, 0)
    is_broad = ovr_count > broad_threshold

    flags: list[str] = []
    if specificity < 0.1:
        flags.append(f"Low specificity ({specificity:.2f}) — matches {(1-specificity)*100:.0f}% of random strings")
    if is_broad:
        flags.append(f"Broad pattern — overlaps with {ovr_count} rules")
    if unique == 0 and actual > 0:
        flags.append("Zero unique coverage — fully redundant")
    if complexity > 50:
        flags.append(f"High complexity ({complexity} AST nodes)")

    log.debug(
        "Rule '%s': specificity=%.2f, fp_potential=%d, complexity=%d, "
        "unique=%d, overlaps=%d%s",
        rule.name, specificity, fp_potential, complexity, unique, ovr_count,
        " [BROAD]" if is_broad else "",
    )

    return RuleQuality(
        name=rule.name,
        source=rule.source,
        specificity=round(specificity, 4),
        false_positive_potential=fp_potential,
        pattern_complexity=complexity,
        unique_coverage=unique,
        is_broad=is_broad,
        overlap_count=ovr_count,
        flags=flags,
    )


def _compute_overlap_counts(
    matrix: MatchMatrix,
    rules: list[Rule],
) -> dict[str, int]:
    """Count how many other rules each rule overlaps with."""
    counts: dict[str, int] = {r.name: 0 for r in rules}
    rule_names = {r.name for r in rules}

    for rule_name, matches in matrix.items():
        if rule_name not in rule_names:
            continue
        for other_name, count in matches.items():
            if other_name != rule_name and count > 0 and other_name in rule_names:
                counts[rule_name] = counts.get(rule_name, 0) + 1

    return counts


def _compute_unique_coverage(
    matrix: MatchMatrix,
    corpus_sizes: dict[str, int],
    rules: list[Rule],
) -> dict[str, int]:
    """Estimate how many corpus strings are NOT matched by any other rule.

    Uses the maximum single-rule overlap as a conservative estimate.
    For exact per-string uniqueness, use real corpus evaluation instead.
    """
    rule_names = {r.name for r in rules}
    unique: dict[str, int] = {r.name: 0 for r in rules}

    for rule in rules:
        own_size = corpus_sizes.get(rule.name, 0)
        # Find the highest overlap from any single other rule
        max_overlap = 0
        for other_name in rule_names:
            if other_name == rule.name:
                continue
            other_matches = matrix.get(other_name, {}).get(rule.name, 0)
            max_overlap = max(max_overlap, other_matches)

        unique[rule.name] = max(0, own_size - max_overlap)

    return unique


def _generate_random_strings(count: int, rng: random.Random) -> list[str]:
    """Generate random strings of varying lengths for specificity testing."""
    strings: list[str] = []
    charset = string.ascii_letters + string.digits + string.punctuation + " "
    lengths = [8, 16, 32, 64, 128]

    for _ in range(count):
        length = rng.choice(lengths)
        s = "".join(rng.choices(charset, k=length))
        strings.append(s)

    return strings


def _pattern_complexity(pattern: str) -> int:
    """Estimate regex complexity by counting AST nodes."""
    try:
        parsed = sre_parse.parse(pattern)
        return _count_nodes(parsed)
    except Exception:
        return 0


def _count_nodes(parsed: sre_parse.SubPattern) -> int:
    """Recursively count nodes in a parsed regex."""
    count = 0
    for op, av in parsed:
        count += 1
        if isinstance(av, sre_parse.SubPattern):
            count += _count_nodes(av)
        elif isinstance(av, (list, tuple)):
            for item in av:
                if isinstance(item, sre_parse.SubPattern):
                    count += _count_nodes(item)
                elif isinstance(item, (list, tuple)):
                    for sub in item:
                        if isinstance(sub, sre_parse.SubPattern):
                            count += _count_nodes(sub)
    return count
