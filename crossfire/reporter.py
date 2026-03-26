"""Output formatting for analysis reports."""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import asdict
from typing import TextIO

from crossfire.models import AnalysisReport, OverlapResult

log = logging.getLogger("crossfire.reporter")


def render_json(report: AnalysisReport, output: TextIO) -> None:
    """Render report as JSON."""
    data = _report_to_dict(report)
    json.dump(data, output, indent=2, default=str)
    output.write("\n")
    log.info("JSON report written (%d bytes)", output.tell() if hasattr(output, "tell") else 0)


def render_table(report: AnalysisReport, output: TextIO) -> None:
    """Render report as a human-readable table."""
    s = report.summary

    output.write(f"\n{'=' * 72}\n")
    output.write(f"  Crossfire Analysis Report — {report.timestamp}\n")
    output.write(
        f"  Rules: {report.input_summary.get('total_rules', 0)} "
        f"from {len(report.input_summary.get('files', []))} file(s) | "  # type: ignore[arg-type]
        f"Corpus: {report.corpus_summary.get('total_strings', 0)} strings | "
        f"Time: {_format_duration(report.evaluation_summary.get('duration_s', 0))}\n"  # type: ignore[arg-type]
    )
    output.write(f"{'=' * 72}\n\n")

    # Duplicates
    if report.duplicates:
        output.write(f"  Duplicates ({len(report.duplicates)} pairs)\n")
        output.write(f"  {'-' * 68}\n")
        output.write(
            f"  {'Rule A':<25} {'Rule B':<25} {'Jaccard':>8} {'Recommendation':>10}\n"
        )
        output.write(f"  {'-' * 68}\n")
        for r in report.duplicates:
            src_a = _short_source(r.source_a)
            src_b = _short_source(r.source_b)
            output.write(
                f"  {r.rule_a:<25} {r.rule_b:<25} {r.jaccard:>7.2f} "
                f" {_short_rec(r.recommendation):>10}\n"
            )
        output.write("\n")

    # Subsets
    subsets = report.subsets
    if subsets:
        output.write(f"  Subsets ({len(subsets)} pairs)\n")
        output.write(f"  {'-' * 68}\n")
        output.write(
            f"  {'Subset Rule':<25} {'Superset Rule':<25} {'A->B %':>8} {'Recommendation':>10}\n"
        )
        output.write(f"  {'-' * 68}\n")
        for r in subsets:
            pct = r.overlap_a_to_b if r.relationship == "subset" else r.overlap_b_to_a
            output.write(
                f"  {r.rule_a:<25} {r.rule_b:<25} {pct * 100:>7.0f}% "
                f" {_short_rec(r.recommendation):>10}\n"
            )
        output.write("\n")

    # Overlaps
    if report.overlaps:
        output.write(f"  Overlaps ({len(report.overlaps)} pairs)\n")
        output.write(f"  {'-' * 68}\n")
        output.write(
            f"  {'Rule A':<25} {'Rule B':<25} {'A->B %':>8} {'B->A %':>8}\n"
        )
        output.write(f"  {'-' * 68}\n")
        for r in report.overlaps:
            output.write(
                f"  {r.rule_a:<25} {r.rule_b:<25} "
                f"{r.overlap_a_to_b * 100:>7.0f}% {r.overlap_b_to_a * 100:>7.0f}%\n"
            )
        output.write("\n")

    # Clusters
    if report.clusters:
        output.write(f"  Clusters ({len(report.clusters)} groups)\n")
        output.write(f"  {'-' * 68}\n")
        for c in report.clusters:
            output.write(f"  Cluster {c.id}: {', '.join(c.rules)}\n")
            output.write(f"    Keep: {c.keep} ({c.reason})\n")
        output.write("\n")

    # Summary
    output.write(f"  Summary: ")
    parts = []
    if s.get("duplicate_pairs"):
        parts.append(f"Drop {s.get('rules_recommended_drop', 0)} rules")
    if s.get("rules_recommended_review"):
        parts.append(f"review {s['rules_recommended_review']}")
    if not parts:
        parts.append("No duplicates or overlaps found")
    output.write(", ".join(parts))
    output.write("\n\n")

    log.info("Table report rendered")


def render_csv(report: AnalysisReport, output: TextIO) -> None:
    """Render report as CSV (one row per overlapping pair)."""
    writer = csv.writer(output)
    writer.writerow([
        "rule_a", "rule_b", "source_a", "source_b",
        "overlap_a_to_b", "overlap_b_to_a", "jaccard",
        "relationship", "recommendation", "reason",
    ])

    all_results = report.duplicates + report.subsets + report.overlaps
    for r in all_results:
        writer.writerow([
            r.rule_a, r.rule_b, r.source_a, r.source_b,
            f"{r.overlap_a_to_b:.4f}", f"{r.overlap_b_to_a:.4f}", f"{r.jaccard:.4f}",
            r.relationship, r.recommendation, r.reason,
        ])

    log.info("CSV report written (%d rows)", len(all_results))


def render_summary(report: AnalysisReport, output: TextIO) -> None:
    """Render a one-paragraph summary."""
    s = report.summary
    total = report.input_summary.get("total_rules", 0)
    files = len(report.input_summary.get("files", []))  # type: ignore[arg-type]
    dups = s.get("duplicate_pairs", 0)
    subs = s.get("subset_pairs", 0)
    overlaps = s.get("overlap_pairs", 0)
    clusters = s.get("clusters", 0)
    drop = s.get("rules_recommended_drop", 0)
    review = s.get("rules_recommended_review", 0)

    output.write(
        f"Analyzed {total} rules from {files} file(s). "
        f"Found {dups} duplicate pair(s), {subs} subset pair(s), "
        f"and {overlaps} partial overlap(s) across {clusters} cluster(s). "
    )
    if drop or review:
        output.write(
            f"Recommendation: drop {drop} rule(s), review {review} rule(s)."
        )
    else:
        output.write("No duplicates detected.")
    output.write("\n")

    log.info("Summary report rendered")


RENDERERS = {
    "json": render_json,
    "table": render_table,
    "csv": render_csv,
    "summary": render_summary,
}


def render(report: AnalysisReport, format: str, output: TextIO) -> None:
    """Render report in the specified format."""
    renderer = RENDERERS.get(format)
    if not renderer:
        raise ValueError(f"Unknown format: {format}. Available: {', '.join(RENDERERS)}")
    renderer(report, output)


def _report_to_dict(report: AnalysisReport) -> dict:
    """Convert report to a JSON-serializable dict."""
    return {
        "crossfire_version": report.crossfire_version,
        "timestamp": report.timestamp,
        "config": report.config,
        "input": report.input_summary,
        "corpus": report.corpus_summary,
        "evaluation": report.evaluation_summary,
        "results": {
            "duplicates": [asdict(r) for r in report.duplicates],
            "subsets": [asdict(r) for r in report.subsets],
            "overlaps": [asdict(r) for r in report.overlaps],
            "clusters": [asdict(c) for c in report.clusters],
        },
        "summary": report.summary,
    }


def _short_source(source: str) -> str:
    """Shorten a source path for display."""
    if not source:
        return ""
    parts = source.rsplit("/", 1)
    return parts[-1] if len(parts) > 1 else source


def _short_rec(rec: str) -> str:
    """Shorten recommendation for table display."""
    return {
        "keep_a": "Keep A",
        "keep_b": "Keep B",
        "keep_both": "Keep both",
        "review": "Review",
    }.get(rec, rec)


def _format_duration(seconds: object) -> str:
    """Format duration in human-readable form."""
    s = float(seconds) if seconds else 0.0
    if s < 60:
        return f"{s:.1f}s"
    m = int(s // 60)
    remaining = s - m * 60
    if remaining > 0.5:
        return f"{m}m {remaining:.0f}s"
    return f"{m}m"
