"""Tests for the plugin system and GitLeaks adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crossfire.plugins import find_adapter, get_adapters, register_adapter
from crossfire.plugins.gitleaks import GitleaksAdapter
from crossfire.loader import load_rules


GITLEAKS_FIXTURE = str(Path(__file__).parent / "fixtures" / "gitleaks_sample.toml")


class TestPluginRegistry:
    def test_gitleaks_registered(self):
        adapters = get_adapters()
        names = [a.name for a in adapters]
        assert "gitleaks" in names

    def test_find_adapter_for_gitleaks(self):
        adapter = find_adapter(GITLEAKS_FIXTURE)
        assert adapter is not None
        assert adapter.name == "gitleaks"

    def test_find_adapter_for_json(self, sample_rules_path: str):
        adapter = find_adapter(sample_rules_path)
        # JSON files don't have [[rules]] so adapter returns None
        assert adapter is None

    def test_find_adapter_nonexistent(self):
        adapter = find_adapter("/nonexistent/file.toml")
        assert adapter is None


class TestGitleaksAdapter:
    def test_can_load_gitleaks(self):
        adapter = GitleaksAdapter()
        assert adapter.can_load(GITLEAKS_FIXTURE)

    def test_cannot_load_json(self, sample_rules_path: str):
        adapter = GitleaksAdapter()
        assert not adapter.can_load(sample_rules_path)

    def test_cannot_load_plain_toml(self, tmp_path: Path):
        """A TOML without [[rules]] should not be detected as GitLeaks."""
        path = tmp_path / "config.toml"
        path.write_text('[settings]\nkey = "value"\n')
        adapter = GitleaksAdapter()
        assert not adapter.can_load(str(path))

    def test_load_rules(self):
        adapter = GitleaksAdapter()
        rules = adapter.load(GITLEAKS_FIXTURE)
        assert len(rules) == 5

    def test_rule_field_mapping(self):
        adapter = GitleaksAdapter()
        rules = adapter.load(GITLEAKS_FIXTURE)
        aws = next(r for r in rules if r["name"] == "aws-access-token")
        assert "pattern" in aws
        assert aws["detector"] == "secrets"
        assert "aws" in aws["tags"]
        assert aws["severity"] == "critical"  # entropy >= 3.5

    def test_metadata_preserved(self):
        adapter = GitleaksAdapter()
        rules = adapter.load(GITLEAKS_FIXTURE)
        aws = next(r for r in rules if r["name"] == "aws-access-token")
        metadata = aws["metadata"]
        assert metadata["entropy"] == 3.5
        assert metadata["secret_group"] == 1
        assert "akia" in metadata["keywords"]
        assert "description" in metadata

    def test_allowlists_in_metadata(self):
        adapter = GitleaksAdapter()
        rules = adapter.load(GITLEAKS_FIXTURE)
        aws = next(r for r in rules if r["name"] == "aws-access-token")
        assert "allowlists" in aws["metadata"]

    def test_severity_inference(self):
        adapter = GitleaksAdapter()
        rules = adapter.load(GITLEAKS_FIXTURE)
        rules_by_name = {r["name"]: r for r in rules}

        # entropy >= 3.5 → critical
        assert rules_by_name["aws-access-token"]["severity"] == "critical"
        # entropy >= 2.0 → high
        assert rules_by_name["github-pat"]["severity"] == "high"
        assert rules_by_name["stripe-secret-key"]["severity"] == "high"
        # has keywords but no entropy → high
        assert rules_by_name["slack-webhook-url"]["severity"] == "high"
        # no entropy, no keywords → medium
        assert rules_by_name["generic-api-key"]["severity"] == "medium"

    def test_no_rules_section(self, tmp_path: Path):
        path = tmp_path / "empty.toml"
        path.write_text('title = "empty"\n[[rules]]\nid = "x"\nregex = "y"\n')
        adapter = GitleaksAdapter()
        rules = adapter.load(str(path))
        assert len(rules) == 1

    def test_rule_missing_regex(self, tmp_path: Path):
        path = tmp_path / "noreg.toml"
        path.write_text('[[rules]]\nid = "no-regex"\ndescription = "missing"\n')
        adapter = GitleaksAdapter()
        rules = adapter.load(str(path))
        assert len(rules) == 0  # skipped

    def test_rule_missing_id(self, tmp_path: Path):
        path = tmp_path / "noid.toml"
        path.write_text('[[rules]]\nregex = "abc"\ndescription = "missing id"\n')
        adapter = GitleaksAdapter()
        rules = adapter.load(str(path))
        assert len(rules) == 0  # skipped


class TestGitleaksIntegration:
    def test_load_via_loader(self):
        """GitLeaks TOML should be auto-detected and loaded via the main loader."""
        rules = load_rules(GITLEAKS_FIXTURE)
        assert len(rules) == 5
        assert rules[0].name == "aws-access-token"
        assert rules[0].detector == "secrets"
        assert rules[0].compiled is not None

    def test_scan_gitleaks_rules(self):
        """Full scan pipeline should work with GitLeaks rules."""
        from click.testing import CliRunner
        from crossfire.cli import main

        runner = CliRunner()
        result = runner.invoke(main, [
            "scan", GITLEAKS_FIXTURE,
            "--format", "summary",
            "--samples", "20",
            "--seed", "42",
        ])
        assert result.exit_code == 0
        assert "Analyzed 5 rules" in result.output

    def test_validate_gitleaks_rules(self):
        from click.testing import CliRunner
        from crossfire.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["validate", GITLEAKS_FIXTURE])
        assert result.exit_code == 0
        assert "5 valid rules" in result.output

    def test_compare_gitleaks_vs_json(self, sample_rules_path: str):
        """Compare GitLeaks rules against JSON rules."""
        from click.testing import CliRunner
        from crossfire.cli import main

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", GITLEAKS_FIXTURE, sample_rules_path,
            "--format", "summary",
            "--samples", "20",
            "--seed", "42",
        ])
        assert result.exit_code == 0
        assert "Analyzed 10 rules" in result.output  # 5 gitleaks + 5 sample
