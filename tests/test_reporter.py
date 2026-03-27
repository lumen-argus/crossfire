"""Tests for output formatting."""

from __future__ import annotations

import csv
import io
import json

from crossfire.models import (
    AnalysisReport,
    ClusterInfo,
    OverlapResult,
    Recommendation,
    Relationship,
)
from crossfire.reporter import render_csv, render_json, render_summary, render_table


def _make_report(
    duplicates: int = 0,
    subsets: int = 0,
    overlaps: int = 0,
) -> AnalysisReport:
    """Create a test report with the specified number of findings."""
    dup_results = [
        OverlapResult(
            rule_a=f"dup_a_{i}",
            rule_b=f"dup_b_{i}",
            source_a="a.json",
            source_b="b.json",
            a_matches_b_corpus=45,
            b_matches_a_corpus=42,
            a_corpus_size=50,
            b_corpus_size=50,
            overlap_a_to_b=0.9,
            overlap_b_to_a=0.84,
            jaccard=0.87,
            relationship=Relationship.DUPLICATE,
            recommendation=Recommendation.KEEP_A,
            reason="Higher priority",
        )
        for i in range(duplicates)
    ]
    sub_results = [
        OverlapResult(
            rule_a=f"sub_a_{i}",
            rule_b=f"sub_b_{i}",
            source_a="a.json",
            source_b="b.json",
            a_matches_b_corpus=48,
            b_matches_a_corpus=10,
            a_corpus_size=50,
            b_corpus_size=50,
            overlap_a_to_b=0.96,
            overlap_b_to_a=0.2,
            jaccard=0.55,
            relationship=Relationship.SUBSET,
            recommendation=Recommendation.KEEP_A,
            reason="More comprehensive",
        )
        for i in range(subsets)
    ]
    ovr_results = [
        OverlapResult(
            rule_a=f"ovr_a_{i}",
            rule_b=f"ovr_b_{i}",
            source_a="a.json",
            source_b="b.json",
            a_matches_b_corpus=20,
            b_matches_a_corpus=15,
            a_corpus_size=50,
            b_corpus_size=50,
            overlap_a_to_b=0.4,
            overlap_b_to_a=0.3,
            jaccard=0.3,
            relationship=Relationship.OVERLAP,
            recommendation=Recommendation.REVIEW,
            reason="Partial overlap",
        )
        for i in range(overlaps)
    ]
    clusters = []
    if duplicates > 0:
        clusters.append(
            ClusterInfo(
                id=1,
                rules=["dup_a_0", "dup_b_0"],
                keep="dup_a_0",
                reason="Highest priority",
            )
        )

    return AnalysisReport(
        crossfire_version="0.1.0",
        timestamp="2026-03-26T14:00:00Z",
        config={"threshold": 0.8, "samples_per_rule": 50},
        input_summary={"files": ["a.json", "b.json"], "total_rules": 100},
        corpus_summary={"total_strings": 5000},
        evaluation_summary={"duration_s": 12.5, "positive_matches": 1234},
        duplicates=dup_results,
        subsets=sub_results,
        overlaps=ovr_results,
        clusters=clusters,
        summary={
            "duplicate_pairs": duplicates,
            "subset_pairs": subsets,
            "overlap_pairs": overlaps,
            "clusters": len(clusters),
            "rules_recommended_drop": duplicates + subsets,
            "rules_recommended_review": overlaps,
        },
    )


class TestJsonRenderer:
    def test_valid_json(self):
        report = _make_report(duplicates=2, subsets=1, overlaps=3)
        buf = io.StringIO()
        render_json(report, buf)
        data = json.loads(buf.getvalue())
        assert data["crossfire_version"] == "0.1.0"
        assert len(data["results"]["duplicates"]) == 2
        assert len(data["results"]["subsets"]) == 1
        assert len(data["results"]["overlaps"]) == 3

    def test_empty_report(self):
        report = _make_report()
        buf = io.StringIO()
        render_json(report, buf)
        data = json.loads(buf.getvalue())
        assert data["results"]["duplicates"] == []
        assert data["summary"]["duplicate_pairs"] == 0

    def test_json_structure(self):
        report = _make_report(duplicates=1)
        buf = io.StringIO()
        render_json(report, buf)
        data = json.loads(buf.getvalue())
        dup = data["results"]["duplicates"][0]
        assert "rule_a" in dup
        assert "rule_b" in dup
        assert "jaccard" in dup
        assert "recommendation" in dup


class TestTableRenderer:
    def test_renders_header(self):
        report = _make_report(duplicates=1)
        buf = io.StringIO()
        render_table(report, buf)
        output = buf.getvalue()
        assert "Crossfire Analysis Report" in output
        assert "2026-03-26" in output

    def test_renders_duplicates(self):
        report = _make_report(duplicates=2)
        buf = io.StringIO()
        render_table(report, buf)
        output = buf.getvalue()
        assert "Duplicates (2 pairs)" in output
        assert "dup_a_0" in output

    def test_renders_subsets(self):
        report = _make_report(subsets=1)
        buf = io.StringIO()
        render_table(report, buf)
        output = buf.getvalue()
        assert "Subsets (1 pairs)" in output

    def test_renders_clusters(self):
        report = _make_report(duplicates=1)
        buf = io.StringIO()
        render_table(report, buf)
        output = buf.getvalue()
        assert "Cluster 1" in output

    def test_empty_report(self):
        report = _make_report()
        buf = io.StringIO()
        render_table(report, buf)
        output = buf.getvalue()
        assert "No duplicates or overlaps found" in output


class TestCsvRenderer:
    def test_csv_header(self):
        report = _make_report(duplicates=1)
        buf = io.StringIO()
        render_csv(report, buf)
        buf.seek(0)
        reader = csv.reader(buf)
        header = next(reader)
        assert "rule_a" in header
        assert "jaccard" in header
        assert "recommendation" in header

    def test_csv_rows(self):
        report = _make_report(duplicates=2, overlaps=1)
        buf = io.StringIO()
        render_csv(report, buf)
        buf.seek(0)
        reader = csv.reader(buf)
        rows = list(reader)
        assert len(rows) == 4  # 1 header + 2 dups + 1 overlap

    def test_empty_csv(self):
        report = _make_report()
        buf = io.StringIO()
        render_csv(report, buf)
        buf.seek(0)
        reader = csv.reader(buf)
        rows = list(reader)
        assert len(rows) == 1  # header only


class TestSummaryRenderer:
    def test_summary_with_findings(self):
        report = _make_report(duplicates=5, subsets=3, overlaps=7)
        buf = io.StringIO()
        render_summary(report, buf)
        output = buf.getvalue()
        assert "5 duplicate" in output
        assert "3 subset" in output
        assert "7 partial overlap" in output

    def test_summary_clean(self):
        report = _make_report()
        buf = io.StringIO()
        render_summary(report, buf)
        output = buf.getvalue()
        assert "No duplicates detected" in output
