"""Tests for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from crossfire.cli import main


class TestValidateCommand:
    def test_valid_file(self, sample_rules_path: str):
        runner = CliRunner()
        result = runner.invoke(main, ["validate", sample_rules_path])
        assert result.exit_code == 0
        assert "5 valid rules" in result.output

    def test_invalid_regex(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps([{"name": "broken", "pattern": "[a-z(+"}]))
        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(path)])
        assert result.exit_code == 2
        assert "ERROR" in result.output

    def test_multiple_files(self, sample_rules_path: str, disjoint_rules_path: str):
        runner = CliRunner()
        result = runner.invoke(main, ["validate", sample_rules_path, disjoint_rules_path])
        assert result.exit_code == 0
        assert "8 rules valid" in result.output

    def test_skip_invalid(self, tmp_path: Path):
        path = tmp_path / "mixed.json"
        path.write_text(json.dumps([
            {"name": "broken", "pattern": "[a-z(+"},
            {"name": "valid", "pattern": "[a-z]+"},
        ]))
        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(path), "--skip-invalid"])
        assert result.exit_code == 0
        assert "1 valid rules" in result.output


class TestScanCommand:
    def test_scan_overlapping(self, overlapping_rules_path: str):
        runner = CliRunner()
        result = runner.invoke(main, [
            "scan", overlapping_rules_path,
            "--format", "json",
            "--samples", "30",
            "--seed", "42",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["input"]["total_rules"] == 7
        # aws_key_v1 and aws_key_v2 should be detected as duplicates
        dup_names = [(d["rule_a"], d["rule_b"]) for d in data["results"]["duplicates"]]
        assert any(
            ("aws_key_v1" in pair and "aws_key_v2" in pair)
            for pair in [set(p) for p in dup_names]
        ), f"Expected aws_key_v1/v2 duplicate, got: {dup_names}"

    def test_scan_disjoint(self, disjoint_rules_path: str):
        runner = CliRunner()
        result = runner.invoke(main, [
            "scan", disjoint_rules_path,
            "--format", "json",
            "--samples", "30",
            "--seed", "42",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["results"]["duplicates"]) == 0

    def test_scan_table_format(self, overlapping_rules_path: str):
        runner = CliRunner()
        result = runner.invoke(main, [
            "scan", overlapping_rules_path,
            "--format", "table",
            "--samples", "20",
            "--seed", "42",
        ])
        assert result.exit_code == 0
        assert "Crossfire Analysis Report" in result.output

    def test_fail_on_duplicate(self, overlapping_rules_path: str):
        runner = CliRunner()
        result = runner.invoke(main, [
            "scan", overlapping_rules_path,
            "--format", "summary",
            "--samples", "30",
            "--seed", "42",
            "--fail-on-duplicate",
        ])
        # Should exit 1 because overlapping.json has duplicates
        assert result.exit_code == 1

    def test_output_to_file(self, overlapping_rules_path: str, tmp_path: Path):
        out_path = tmp_path / "report.json"
        runner = CliRunner()
        result = runner.invoke(main, [
            "scan", overlapping_rules_path,
            "--format", "json",
            "--output", str(out_path),
            "--samples", "20",
            "--seed", "42",
        ])
        assert result.exit_code == 0
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert "results" in data


class TestCompareCommand:
    def test_compare_two_files(self, sample_rules_path: str, disjoint_rules_path: str):
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", sample_rules_path, disjoint_rules_path,
            "--format", "json",
            "--samples", "20",
            "--seed", "42",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["input"]["total_rules"] == 8


class TestGenerateCorpusCommand:
    def test_generate_corpus(self, sample_rules_path: str, tmp_path: Path):
        out_path = tmp_path / "corpus.json"
        runner = CliRunner()
        result = runner.invoke(main, [
            "generate-corpus", sample_rules_path,
            "--output", str(out_path),
            "--samples", "10",
            "--seed", "42",
        ])
        assert result.exit_code == 0
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert len(data) > 0
        assert "text" in data[0]
        assert "source_rule" in data[0]


class TestGlobalOptions:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_log_level(self, sample_rules_path: str):
        runner = CliRunner()
        result = runner.invoke(main, [
            "--log-level", "debug",
            "validate", sample_rules_path,
        ])
        assert result.exit_code == 0
