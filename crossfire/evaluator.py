"""Cross-rule evaluation engine."""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from crossfire.models import CompiledPattern, CorpusEntry, Rule

log = logging.getLogger("crossfire.evaluator")

# Type alias for the match matrix: matrix[rule_name][corpus_source_rule] = match_count
MatchMatrix = dict[str, dict[str, int]]

# Fork is safe on Linux; macOS/Windows use spawn (fork unsafe with Obj-C runtime / not supported)
_USE_FORK = sys.platform == "linux"

# ---- Fork-mode shared data (set before pool creation, inherited via COW) ----
_fork_compiled: list[tuple[str, CompiledPattern]] = []
_fork_corpus: list[tuple[str, str]] = []


def _evaluate_fork_chunk(
    chunk_range: tuple[int, int],
) -> list[tuple[str, str, int]]:
    """Evaluate pre-compiled rules against a corpus slice (fork mode).

    Workers inherit compiled patterns and corpus from the parent process
    via copy-on-write. No serialization, no recompilation, and RE2-compiled
    patterns work transparently.

    Args:
        chunk_range: (start, end) indices into the shared corpus.

    Returns:
        List of (rule_name, source_rule, match_count) tuples.
    """
    start, end = chunk_range
    results: list[tuple[str, str, int]] = []

    for rule_name, compiled in _fork_compiled:
        counts: dict[str, int] = defaultdict(int)
        for i in range(start, end):
            text, source_rule = _fork_corpus[i]
            if compiled.search(text):
                counts[source_rule] += 1
        for source_rule, count in counts.items():
            results.append((rule_name, source_rule, count))

    return results


def _evaluate_spawn_chunk(
    rule_patterns: list[tuple[str, str]],
    corpus_chunk: list[tuple[str, str]],
) -> list[tuple[str, str, int]]:
    """Evaluate rules against a corpus chunk (spawn mode).

    Workers recompile patterns from strings since Pattern objects are not
    picklable. Used on macOS/Windows where fork is unavailable.

    Args:
        rule_patterns: List of (rule_name, pattern_string) tuples — all rules.
        corpus_chunk: List of (text, source_rule) tuples — a slice of corpus.

    Returns:
        List of (rule_name, source_rule, match_count) tuples.
    """
    import re

    compiled_rules: list[tuple[str, re.Pattern[str]]] = []
    for rule_name, pattern in rule_patterns:
        try:
            compiled_rules.append((rule_name, re.compile(pattern)))
        except re.error:
            continue

    counts: dict[tuple[str, str], int] = defaultdict(int)
    for text, source_rule in corpus_chunk:
        for rule_name, compiled in compiled_rules:
            if compiled.search(text):
                counts[(rule_name, source_rule)] += 1

    return [(rn, sr, c) for (rn, sr), c in counts.items()]


class Evaluator:
    """Cross-evaluates all rules against all corpus strings.

    Builds an NxN match matrix showing how many of each rule's corpus
    strings are matched by every other rule.

    On Linux, uses fork-based workers that inherit pre-compiled patterns
    (including RE2) via copy-on-write — zero serialization and recompilation.
    On macOS/Windows, falls back to spawn-based workers that recompile from
    pattern strings.
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

        n_workers = self.workers or os.cpu_count() or 4
        if n_workers == 1 or len(corpus_texts) < 50 or len(rules) < 2:
            return self._evaluate_single_thread(rules, corpus)

        if _USE_FORK:
            return self._evaluate_fork(rules, corpus_texts, n_workers)
        return self._evaluate_spawn(rules, corpus_texts, n_workers)

    def _evaluate_fork(
        self,
        rules: list[Rule],
        corpus_texts: list[tuple[str, str]],
        n_workers: int,
    ) -> MatchMatrix:
        """Fork mode: workers inherit pre-compiled patterns via COW.

        Zero serialization for patterns/corpus. RE2-compiled patterns
        (from loader) are used directly. Only (start, end) integers are
        sent to workers.
        """
        global _fork_compiled, _fork_corpus
        _fork_compiled = [(r.name, r.compiled) for r in rules]
        _fork_corpus = corpus_texts

        chunk_size = max(1, -(-len(corpus_texts) // n_workers))  # ceil division
        chunk_ranges = [
            (i, min(i + chunk_size, len(corpus_texts)))
            for i in range(0, len(corpus_texts), chunk_size)
        ]

        ctx = multiprocessing.get_context("fork")
        matrix: MatchMatrix = defaultdict(lambda: defaultdict(int))
        completed = 0
        failed: list[tuple[int, Exception]] = []

        try:
            with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as executor:
                futures = {
                    executor.submit(_evaluate_fork_chunk, cr): i
                    for i, cr in enumerate(chunk_ranges)
                }

                for future in as_completed(futures):
                    chunk_idx = futures[future]
                    try:
                        results = future.result()
                        for rule_name, source_rule, count in results:
                            matrix[rule_name][source_rule] += count
                    except Exception as exc:
                        log.error("Worker chunk %d failed", chunk_idx, exc_info=True)
                        failed.append((chunk_idx, exc))

                    completed += 1
                    n_chunks = len(chunk_ranges)
                    if completed == n_chunks or completed % max(1, n_chunks // 4) == 0:
                        pct = int(completed / n_chunks * 100)
                        log.info("Progress: %d%% (%d/%d chunks)", pct, completed, n_chunks)
        finally:
            _fork_compiled = []
            _fork_corpus = []

        if failed:
            raise RuntimeError(
                f"{len(failed)} evaluation worker(s) failed — results would be incomplete"
            )

        return dict(matrix)

    def _evaluate_spawn(
        self,
        rules: list[Rule],
        corpus_texts: list[tuple[str, str]],
        n_workers: int,
    ) -> MatchMatrix:
        """Spawn mode: workers recompile patterns from strings.

        Used on macOS/Windows where fork is unavailable. Each worker
        receives pattern strings and a corpus slice.
        """
        rule_patterns = [(r.name, r.pattern) for r in rules]

        chunk_size = max(1, -(-len(corpus_texts) // n_workers))  # ceil division
        chunks = [corpus_texts[i : i + chunk_size] for i in range(0, len(corpus_texts), chunk_size)]

        matrix: MatchMatrix = defaultdict(lambda: defaultdict(int))
        completed = 0
        failed: list[tuple[int, Exception]] = []

        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(_evaluate_spawn_chunk, rule_patterns, chunk): i
                for i, chunk in enumerate(chunks)
            }

            for future in as_completed(futures):
                chunk_idx = futures[future]
                try:
                    results = future.result()
                    for rule_name, source_rule, count in results:
                        matrix[rule_name][source_rule] += count
                except Exception as exc:
                    log.error("Worker chunk %d failed", chunk_idx, exc_info=True)
                    failed.append((chunk_idx, exc))

                completed += 1
                if completed == len(chunks) or completed % max(1, len(chunks) // 4) == 0:
                    pct = int(completed / len(chunks) * 100)
                    log.info("Progress: %d%% (%d/%d chunks)", pct, completed, len(chunks))

        if failed:
            raise RuntimeError(
                f"{len(failed)} evaluation worker(s) failed — results would be incomplete"
            )

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
