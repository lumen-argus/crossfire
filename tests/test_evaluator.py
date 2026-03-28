"""Tests for cross-rule evaluation."""

from __future__ import annotations

import re

from crossfire.evaluator import Evaluator
from crossfire.models import CorpusEntry, Rule


def _make_rule(name: str, pattern: str, detector: str = "") -> Rule:
    return Rule(name=name, pattern=pattern, compiled=re.compile(pattern), detector=detector)


def _make_entry(text: str, source_rule: str) -> CorpusEntry:
    return CorpusEntry(text=text, source_rule=source_rule)


class TestSingleThread:
    def test_self_match(self):
        """A rule should match its own corpus strings."""
        rules = [_make_rule("digits", r"\d{4}")]
        corpus = [
            _make_entry("1234", "digits"),
            _make_entry("5678", "digits"),
        ]
        evaluator = Evaluator(workers=1)
        matrix = evaluator.evaluate(rules, corpus)
        assert matrix["digits"]["digits"] == 2

    def test_no_cross_match(self):
        """Disjoint rules should not match each other's corpus."""
        rules = [
            _make_rule("digits", r"^\d{8}$"),
            _make_rule("letters", r"^[a-z]{8}$"),
        ]
        corpus = [
            _make_entry("12345678", "digits"),
            _make_entry("abcdefgh", "letters"),
        ]
        evaluator = Evaluator(workers=1)
        matrix = evaluator.evaluate(rules, corpus)
        assert matrix.get("digits", {}).get("letters", 0) == 0
        assert matrix.get("letters", {}).get("digits", 0) == 0

    def test_subset_match(self):
        """A broad rule should match a specific rule's corpus."""
        rules = [
            _make_rule("specific", r"^abc\d{3}$"),
            _make_rule("broad", r"^[a-z]+\d+$"),
        ]
        corpus = [
            _make_entry("abc123", "specific"),
            _make_entry("abc456", "specific"),
            _make_entry("xyz789", "broad"),
        ]
        evaluator = Evaluator(workers=1)
        matrix = evaluator.evaluate(rules, corpus)
        # broad should match specific's corpus
        assert matrix["broad"]["specific"] == 2
        # specific may or may not match broad's corpus
        # xyz789 doesn't match ^abc\d{3}$

    def test_empty_rules(self):
        evaluator = Evaluator(workers=1)
        matrix = evaluator.evaluate([], [])
        assert matrix == {}

    def test_empty_corpus(self):
        rules = [_make_rule("test", r"\d+")]
        evaluator = Evaluator(workers=1)
        matrix = evaluator.evaluate(rules, [])
        assert matrix == {}

    def test_negative_entries_excluded(self):
        """Negative corpus entries should not be included in evaluation."""
        rules = [_make_rule("test", r"\d{4}")]
        corpus = [
            _make_entry("1234", "test"),
            CorpusEntry(text="abcd", source_rule="test", is_negative=True),
        ]
        evaluator = Evaluator(workers=1)
        matrix = evaluator.evaluate(rules, corpus)
        assert matrix["test"]["test"] == 1  # only the positive entry


class TestParallel:
    def test_parallel_matches_single_thread(self):
        """Parallel evaluation should produce identical results to single-threaded."""
        rules = [
            _make_rule("a", r"[a-z]{5}"),
            _make_rule("b", r"[a-z]{4,6}"),
            _make_rule("c", r"\d{5}"),
        ]
        # Need >= 50 corpus entries to trigger parallel path
        corpus = [
            _make_entry("abcde", "a"),
            _make_entry("fghij", "a"),
            _make_entry("abcd", "b"),
            _make_entry("abcdef", "b"),
            _make_entry("12345", "c"),
        ] * 12  # 60 entries

        single = Evaluator(workers=1)
        matrix_single = single.evaluate(rules, corpus)

        parallel = Evaluator(workers=2)
        matrix_parallel = parallel.evaluate(rules, corpus)

        # Matrices must be identical
        assert set(matrix_single.keys()) == set(matrix_parallel.keys())
        for rule_name in matrix_single:
            assert matrix_single[rule_name] == matrix_parallel[rule_name], (
                f"Mismatch for rule '{rule_name}'"
            )

    def test_corpus_chunk_merging(self):
        """Counts from different corpus chunks must be summed correctly."""
        rules = [
            _make_rule("broad", r"\d+"),
            _make_rule("narrow", r"\d{4}"),
        ]
        # Many entries from same source — will be split across workers
        corpus = [_make_entry("1234", "narrow")] * 100

        parallel = Evaluator(workers=4)
        matrix = parallel.evaluate(rules, corpus)

        assert matrix["broad"]["narrow"] == 100
        assert matrix["narrow"]["narrow"] == 100


class TestPartitioning:
    def test_partition_by_detector(self):
        """Rules in different partitions should not cross-evaluate."""
        rules = [
            _make_rule("secret_rule", r"[a-z]{10}", detector="secrets"),
            _make_rule("pii_rule", r"\d{10}", detector="pii"),
        ]
        corpus = [
            _make_entry("abcdefghij", "secret_rule"),
            _make_entry("1234567890", "pii_rule"),
        ]
        evaluator = Evaluator(workers=1, partition_by="detector")
        matrix = evaluator.evaluate(rules, corpus)

        # secret_rule should only be evaluated against secrets corpus
        # pii_rule should only be evaluated against pii corpus
        # No cross-partition matching
        assert matrix.get("secret_rule", {}).get("pii_rule", 0) == 0
        assert matrix.get("pii_rule", {}).get("secret_rule", 0) == 0

    def test_same_partition_cross_evaluates(self):
        """Rules in the same partition should cross-evaluate."""
        rules = [
            _make_rule("rule_a", r"[a-f]{10}", detector="secrets"),
            _make_rule("rule_b", r"[a-z]{10}", detector="secrets"),
        ]
        corpus = [
            _make_entry("abcdefabcd", "rule_a"),
        ]
        evaluator = Evaluator(workers=1, partition_by="detector")
        matrix = evaluator.evaluate(rules, corpus)
        # rule_b (broader) should match rule_a's corpus
        assert matrix.get("rule_b", {}).get("rule_a", 0) == 1


class TestMatchMatrix:
    def test_matrix_structure(self):
        rules = [
            _make_rule("a", r"\d{4}"),
            _make_rule("b", r"\d{3,5}"),
        ]
        corpus = [
            _make_entry("1234", "a"),
            _make_entry("5678", "a"),
            _make_entry("123", "b"),
            _make_entry("12345", "b"),
        ]
        evaluator = Evaluator(workers=1)
        matrix = evaluator.evaluate(rules, corpus)

        # matrix[rule_name] is a dict of {source_rule: count}
        assert isinstance(matrix, dict)
        for counts in matrix.values():
            assert isinstance(counts, dict)
            for count in counts.values():
                assert isinstance(count, int)
                assert count >= 0
