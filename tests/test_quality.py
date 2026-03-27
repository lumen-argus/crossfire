"""Tests for quality scoring and broad pattern detection."""

from __future__ import annotations

import re

from crossfire.models import CorpusEntry, Rule
from crossfire.quality import (
    QualityReport,
    _compute_overlap_counts,
    _compute_unique_coverage,
    _pattern_complexity,
    assess_quality,
)


def _make_rule(name: str, pattern: str, source: str = "test") -> Rule:
    return Rule(name=name, pattern=pattern, compiled=re.compile(pattern), source=source)


class TestPatternComplexity:
    def test_simple_literal(self):
        c = _pattern_complexity("abc")
        assert c > 0  # at least 3 literal nodes

    def test_character_class(self):
        c = _pattern_complexity("[a-z]+")
        assert c > 0

    def test_alternation_more_complex(self):
        c_simple = _pattern_complexity("abc")
        c_alt = _pattern_complexity("(abc|def|ghi)")
        assert c_alt > c_simple

    def test_invalid_pattern_returns_zero(self):
        c = _pattern_complexity("[invalid(")
        assert c == 0


class TestOverlapCounts:
    def test_no_overlaps(self):
        rules = [_make_rule("a", "x"), _make_rule("b", "y")]
        matrix = {"a": {"a": 10}, "b": {"b": 10}}
        counts = _compute_overlap_counts(matrix, rules)
        assert counts["a"] == 0
        assert counts["b"] == 0

    def test_mutual_overlap(self):
        rules = [_make_rule("a", "x"), _make_rule("b", "y")]
        matrix = {"a": {"a": 10, "b": 5}, "b": {"a": 5, "b": 10}}
        counts = _compute_overlap_counts(matrix, rules)
        assert counts["a"] == 1
        assert counts["b"] == 1

    def test_broad_pattern(self):
        rules = [
            _make_rule("broad", "x"),
            _make_rule("a", "x"),
            _make_rule("b", "x"),
            _make_rule("c", "x"),
        ]
        matrix = {
            "broad": {"broad": 10, "a": 5, "b": 5, "c": 5},
            "a": {"a": 10},
            "b": {"b": 10},
            "c": {"c": 10},
        }
        counts = _compute_overlap_counts(matrix, rules)
        assert counts["broad"] == 3


class TestUniqueCoverage:
    def test_all_unique(self):
        rules = [_make_rule("a", "x"), _make_rule("b", "y")]
        corpus_sizes = {"a": 1, "b": 1}
        matrix = {"a": {"a": 1}, "b": {"b": 1}}
        unique = _compute_unique_coverage(matrix, corpus_sizes, rules)
        assert unique["a"] == 1
        assert unique["b"] == 1

    def test_fully_overlapped(self):
        rules = [_make_rule("specific", "x"), _make_rule("broad", "y")]
        corpus_sizes = {"specific": 2, "broad": 5}
        # broad matches all of specific's corpus
        matrix = {
            "specific": {"specific": 2},
            "broad": {"specific": 2, "broad": 5},
        }
        unique = _compute_unique_coverage(matrix, corpus_sizes, rules)
        assert unique["specific"] == 0  # broad covers everything


class TestAssessQuality:
    def test_basic_assessment(self):
        rules = [
            _make_rule("tight", r"^AKIA[0-9A-Z]{16}$"),
            _make_rule("loose", r"[a-zA-Z0-9]+"),
        ]
        corpus = [
            CorpusEntry(text="AKIA1234567890ABCDEF", source_rule="tight"),
        ] + [CorpusEntry(text=f"abc{i}", source_rule="loose") for i in range(10)]
        matrix = {
            "tight": {"tight": 1},
            "loose": {"tight": 1, "loose": 10},
        }
        sizes = {"tight": 1, "loose": 10}

        report = assess_quality(rules, corpus, matrix, sizes, seed=42)
        assert isinstance(report, QualityReport)
        assert len(report.rules) == 2

        # loose should have lower specificity than tight
        tight_q = next(r for r in report.rules if r.name == "tight")
        loose_q = next(r for r in report.rules if r.name == "loose")
        assert tight_q.specificity > loose_q.specificity

    def test_broad_detection(self):
        # Create a rule that overlaps with 6 others (above threshold of 5)
        rules = [_make_rule(f"rule_{i}", "[a-z]{5}") for i in range(7)]
        matrix = {
            "rule_0": {f"rule_{i}": 5 for i in range(7)},
        }
        for i in range(1, 7):
            matrix[f"rule_{i}"] = {f"rule_{i}": 10}

        corpus = [
            CorpusEntry(text=f"abc{i}x", source_rule=f"rule_{i}")
            for i in range(7)
            for _ in range(10)
        ]
        sizes = {f"rule_{i}": 10 for i in range(7)}

        report = assess_quality(
            rules,
            corpus,
            matrix,
            sizes,
            broad_threshold=5,
            seed=42,
        )
        broad_names = [r.name for r in report.broad_patterns]
        assert "rule_0" in broad_names

    def test_empty_rules(self):
        report = assess_quality([], [], {}, {}, seed=42)
        assert len(report.rules) == 0
        assert len(report.broad_patterns) == 0

    def test_flags_generated(self):
        rules = [_make_rule("loose", r".")]  # matches everything
        corpus = [CorpusEntry(text="a", source_rule="loose")]
        matrix = {"loose": {"loose": 1}}
        sizes = {"loose": 1}

        report = assess_quality(rules, corpus, matrix, sizes, seed=42)
        loose_q = report.rules[0]
        assert loose_q.specificity < 0.1
        assert any("specificity" in f.lower() for f in loose_q.flags)


class TestQualityReportSummary:
    def test_summary_fields(self):
        rules = [_make_rule("a", r"[a-z]{10}")]
        corpus = [CorpusEntry(text="abcdefghij", source_rule="a") for _ in range(10)]
        matrix = {"a": {"a": 10}}
        sizes = {"a": 10}

        report = assess_quality(rules, corpus, matrix, sizes, seed=42)
        assert "total_rules" in report.summary
        assert "broad_patterns" in report.summary
        assert "avg_specificity" in report.summary
        assert "avg_complexity" in report.summary
