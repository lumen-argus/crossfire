"""Tests for data models."""

from __future__ import annotations

import re

from crossfire.models import (
    AnalysisReport,
    ClusterInfo,
    CorpusEntry,
    OverlapResult,
    Rule,
)


class TestRule:
    def test_create_minimal(self):
        r = Rule(name="test", pattern="abc", compiled=re.compile("abc"))
        assert r.name == "test"
        assert r.pattern == "abc"
        assert r.source == ""
        assert r.detector == ""
        assert r.severity == ""
        assert r.tags == []
        assert r.priority == 0
        assert r.metadata == {}

    def test_create_full(self):
        r = Rule(
            name="aws_key",
            pattern=r"AKIA[0-9A-Z]{16}",
            compiled=re.compile(r"AKIA[0-9A-Z]{16}"),
            source="pro.json",
            detector="secrets",
            severity="critical",
            tags=["cloud", "aws"],
            priority=100,
            metadata={"action": "block"},
        )
        assert r.detector == "secrets"
        assert r.tags == ["cloud", "aws"]
        assert r.metadata["action"] == "block"

    def test_compiled_matches(self):
        r = Rule(name="test", pattern=r"\d{3}", compiled=re.compile(r"\d{3}"))
        assert r.compiled.search("abc123def")
        assert not r.compiled.search("abcdef")


class TestCorpusEntry:
    def test_positive_entry(self):
        e = CorpusEntry(text="AKIAIOSFODNN7EXAMPLE", source_rule="aws_key")
        assert not e.is_negative

    def test_negative_entry(self):
        e = CorpusEntry(text="not_a_key", source_rule="aws_key", is_negative=True)
        assert e.is_negative


class TestOverlapResult:
    def test_create(self):
        r = OverlapResult(
            rule_a="a", rule_b="b",
            source_a="f1.json", source_b="f2.json",
            a_matches_b_corpus=45, b_matches_a_corpus=48,
            a_corpus_size=50, b_corpus_size=50,
            overlap_a_to_b=0.9, overlap_b_to_a=0.96,
            jaccard=0.88,
            relationship="duplicate",
            recommendation="keep_a",
            reason="Higher priority",
        )
        assert r.relationship == "duplicate"
        assert r.jaccard == 0.88


class TestClusterInfo:
    def test_create(self):
        c = ClusterInfo(id=1, rules=["a", "b", "c"], keep="a", reason="Highest priority")
        assert len(c.rules) == 3
        assert c.keep == "a"


class TestAnalysisReport:
    def test_create_empty(self):
        r = AnalysisReport(
            crossfire_version="0.1.0",
            timestamp="2026-03-26T14:00:00Z",
            config={},
            input_summary={},
            corpus_summary={},
            evaluation_summary={},
            duplicates=[],
            subsets=[],
            overlaps=[],
            clusters=[],
            summary={},
        )
        assert r.crossfire_version == "0.1.0"
        assert r.duplicates == []
