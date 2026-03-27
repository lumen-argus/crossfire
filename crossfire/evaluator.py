"""Cross-rule evaluation engine."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from crossfire.models import CorpusEntry, Rule

log = logging.getLogger("crossfire.evaluator")

# Type alias for the match matrix: matrix[rule_name][corpus_source_rule] = match_count
MatchMatrix = dict[str, dict[str, int]]


def _evaluate_chunk(
    rule_patterns: list[tuple[str, str]],
    corpus_texts: list[tuple[str, str]],
) -> list[tuple[str, str, int]]:
    """Evaluate a chunk of rules against the full corpus.

    This runs in a worker process. We pass pattern strings (not compiled
    objects) and re-compile here because regex Pattern objects are not
    transferable across process boundaries via the standard multiprocessing
    serialization. No pickle of untrusted data is involved — we only
    serialize plain strings and integers.

    Args:
        rule_patterns: List of (rule_name, pattern_string) tuples.
        corpus_texts: List of (text, source_rule) tuples.

    Returns:
        List of (rule_name, source_rule, match_count) tuples.
    """
    import re

    results: list[tuple[str, str, int]] = []

    for rule_name, pattern in rule_patterns:
        try:
            compiled = re.compile(pattern)
        except re.error:
            continue

        counts: dict[str, int] = defaultdict(int)
        for text, source_rule in corpus_texts:
            if compiled.search(text):
                counts[source_rule] += 1

        for source_rule, count in counts.items():
            results.append((rule_name, source_rule, count))

    return results


class Evaluator:
    """Cross-evaluates all rules against all corpus strings.

    Builds an NxN match matrix showing how many of each rule's corpus
    strings are matched by every other rule.
    """

    def __init__(
        self,
        workers: int = 0,
        partition_by: str | None = None,
    ) -> None:
        """Initialize evaluator.

        Args:
            workers: Number of parallel workers. 0 = auto (CPU count).
            partition_by: Field to partition rules by (e.g., 'detector').
                         Only rules with the same partition value are cross-evaluated.
        """
        self.workers = workers if workers > 0 else None  # None = auto
        self.partition_by = partition_by

    def evaluate(
        self,
        rules: list[Rule],
        corpus: list[CorpusEntry],
    ) -> MatchMatrix:
        """Run cross-evaluation of all rules against all corpus entries.

        Args:
            rules: List of rules to evaluate.
            corpus: List of corpus entries (positive only — negatives are excluded).

        Returns:
            Match matrix: matrix[rule_name][corpus_source_rule] = match_count
        """
        # Filter to positive corpus entries only
        positive_corpus = [e for e in corpus if not e.is_negative]

        if not rules or not positive_corpus:
            log.warning("Empty rules or corpus — nothing to evaluate")
            return {}

        total_ops = len(rules) * len(positive_corpus)
        log.info(
            "Cross-evaluation started: %d rules x %d strings = %d matches",
            len(rules),
            len(positive_corpus),
            total_ops,
        )

        t0 = time.monotonic()

        if self.partition_by:
            matrix = self._evaluate_partitioned(rules, positive_corpus)
        else:
            matrix = self._evaluate_all(rules, positive_corpus)

        duration = time.monotonic() - t0
        total_matches = sum(
            count for rule_counts in matrix.values() for count in rule_counts.values()
        )
        log.info(
            "Cross-evaluation complete: %d positive matches in %.1fs",
            total_matches,
            duration,
        )
        return matrix

    def _evaluate_partitioned(
        self,
        rules: list[Rule],
        corpus: list[CorpusEntry],
    ) -> MatchMatrix:
        """Evaluate rules partitioned by detector type."""
        partitions: dict[str, list[Rule]] = defaultdict(list)
        for rule in rules:
            key = getattr(rule, self.partition_by or "detector", "") or "_default"
            partitions[key].append(rule)

        rule_to_partition: dict[str, str] = {}
        for rule in rules:
            key = getattr(rule, self.partition_by or "detector", "") or "_default"
            rule_to_partition[rule.name] = key

        corpus_by_partition: dict[str, list[CorpusEntry]] = defaultdict(list)
        for entry in corpus:
            partition_key = rule_to_partition.get(entry.source_rule, "_default")
            corpus_by_partition[partition_key].append(entry)

        matrix: MatchMatrix = {}
        for partition_key, partition_rules in partitions.items():
            partition_corpus = corpus_by_partition.get(partition_key, [])
            if not partition_corpus:
                continue
            log.info(
                "Evaluating partition '%s': %d rules x %d strings",
                partition_key,
                len(partition_rules),
                len(partition_corpus),
            )
            partition_matrix = self._evaluate_all(partition_rules, partition_corpus)
            matrix.update(partition_matrix)

        return matrix

    def _evaluate_all(
        self,
        rules: list[Rule],
        corpus: list[CorpusEntry],
    ) -> MatchMatrix:
        """Evaluate all rules against all corpus entries using parallel workers."""
        corpus_texts = [(e.text, e.source_rule) for e in corpus]
        rule_patterns = [(r.name, r.pattern) for r in rules]

        # Decide chunk size
        n_workers = self.workers or 4
        if len(rules) <= n_workers or len(rules) < 10:
            return self._evaluate_single_thread(rules, corpus)

        chunk_size = max(1, len(rule_patterns) // n_workers)
        chunks = [
            rule_patterns[i : i + chunk_size] for i in range(0, len(rule_patterns), chunk_size)
        ]

        matrix: MatchMatrix = defaultdict(lambda: defaultdict(int))
        completed = 0

        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(_evaluate_chunk, chunk, corpus_texts): i
                for i, chunk in enumerate(chunks)
            }

            for future in as_completed(futures):
                chunk_idx = futures[future]
                try:
                    results = future.result()
                    for rule_name, source_rule, count in results:
                        matrix[rule_name][source_rule] = count
                except Exception:
                    log.error("Worker chunk %d failed", chunk_idx, exc_info=True)

                completed += 1
                pct = int(completed / len(chunks) * 100)
                if pct % 25 == 0 or completed == len(chunks):
                    log.info("Progress: %d%% (%d/%d chunks)", pct, completed, len(chunks))

        return dict(matrix)

    def _evaluate_single_thread(
        self,
        rules: list[Rule],
        corpus: list[CorpusEntry],
    ) -> MatchMatrix:
        """Single-threaded evaluation for small rule sets."""
        matrix: MatchMatrix = defaultdict(lambda: defaultdict(int))

        for rule in rules:
            for entry in corpus:
                if rule.compiled.search(entry.text):
                    matrix[rule.name][entry.source_rule] += 1

        return dict(matrix)
