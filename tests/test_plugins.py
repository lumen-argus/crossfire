"""Tests for the plugin system and GitLeaks adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crossfire.plugins import find_adapter, get_adapters, register_adapter
from crossfire.plugins.gitleaks import GitleaksAdapter
from crossfire.plugins.semgrep import SemgrepAdapter
from crossfire.plugins.yara import YaraAdapter
from crossfire.plugins.sigma import SigmaAdapter
from crossfire.plugins.snort import SnortAdapter
from crossfire.loader import load_rules

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GITLEAKS_FIXTURE = str(FIXTURES_DIR / "gitleaks_sample.toml")
SEMGREP_FIXTURE = str(FIXTURES_DIR / "semgrep_sample.yaml")
YARA_FIXTURE = str(FIXTURES_DIR / "yara_sample.yar")
SIGMA_FIXTURE = str(FIXTURES_DIR / "sigma_sample.yaml")
SNORT_FIXTURE = str(FIXTURES_DIR / "snort_sample.rules")


class TestPluginRegistry:
    def test_all_adapters_registered(self):
        adapters = get_adapters()
        names = [a.name for a in adapters]
        assert "gitleaks" in names
        assert "semgrep" in names
        assert "yara" in names
        assert "snort" in names

    def test_find_adapter_for_gitleaks(self):
        adapter = find_adapter(GITLEAKS_FIXTURE)
        assert adapter is not None
        assert adapter.name == "gitleaks"

    def test_find_adapter_for_semgrep(self):
        adapter = find_adapter(SEMGREP_FIXTURE)
        assert adapter is not None
        assert adapter.name == "semgrep"

    def test_find_adapter_for_yara(self):
        adapter = find_adapter(YARA_FIXTURE)
        assert adapter is not None
        assert adapter.name == "yara"

    def test_find_adapter_for_snort(self):
        adapter = find_adapter(SNORT_FIXTURE)
        assert adapter is not None
        assert adapter.name == "snort"

    def test_find_adapter_for_json(self, sample_rules_path: str):
        adapter = find_adapter(sample_rules_path)
        # JSON files have no matching adapter
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

    def test_metadata_not_nested(self):
        """Adapter metadata should be used directly, not wrapped in extra dict."""
        rules = load_rules(GITLEAKS_FIXTURE)
        aws = next(r for r in rules if r.name == "aws-access-token")
        # metadata should contain entropy directly, not {"metadata": {"entropy": ...}}
        assert "entropy" in aws.metadata
        assert "metadata" not in aws.metadata
        assert aws.metadata["entropy"] == 3.5

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


class TestSemgrepAdapter:
    def test_can_load(self):
        adapter = SemgrepAdapter()
        assert adapter.can_load(SEMGREP_FIXTURE)

    def test_cannot_load_non_semgrep_yaml(self, tmp_path: Path):
        path = tmp_path / "plain.yaml"
        path.write_text("key: value\n")
        adapter = SemgrepAdapter()
        assert not adapter.can_load(str(path))

    def test_load_rules(self):
        adapter = SemgrepAdapter()
        rules = adapter.load(SEMGREP_FIXTURE)
        # 3 top-level regex rules + 1 from patterns block (hardcoded-password has pattern-regex)
        # ast-only-rule is skipped (no pattern-regex)
        assert len(rules) >= 4
        names = [r["name"] for r in rules]
        assert "aws-access-key-id" in names
        assert "generic-api-key" in names
        assert "private-key-pem" in names

    def test_ast_only_skipped(self):
        adapter = SemgrepAdapter()
        rules = adapter.load(SEMGREP_FIXTURE)
        names = [r["name"] for r in rules]
        assert "ast-only-rule" not in names

    def test_severity_mapping(self):
        adapter = SemgrepAdapter()
        rules = adapter.load(SEMGREP_FIXTURE)
        by_name = {r["name"]: r for r in rules}
        assert by_name["aws-access-key-id"]["severity"] == "critical"  # ERROR
        assert by_name["generic-api-key"]["severity"] == "high"  # WARNING

    def test_load_via_loader(self):
        rules = load_rules(SEMGREP_FIXTURE)
        assert len(rules) >= 4
        assert rules[0].detector == "secrets"

    def test_scan_semgrep(self):
        from click.testing import CliRunner
        from crossfire.cli import main

        runner = CliRunner()
        result = runner.invoke(main, [
            "scan", SEMGREP_FIXTURE,
            "--format", "summary",
            "--samples", "20",
            "--seed", "42",
            "--skip-invalid",
        ])
        assert result.exit_code == 0
        assert "Analyzed" in result.output


class TestYaraAdapter:
    def test_can_load(self):
        adapter = YaraAdapter()
        assert adapter.can_load(YARA_FIXTURE)

    def test_cannot_load_non_yara(self, tmp_path: Path):
        path = tmp_path / "test.yar"
        path.write_text("not a yara file\n")
        adapter = YaraAdapter()
        assert not adapter.can_load(str(path))

    def test_load_rules(self):
        adapter = YaraAdapter()
        rules = adapter.load(YARA_FIXTURE)
        # Detect_AWS_Key: 2 regex strings, Detect_Base64_Credentials: 2 regex strings
        # Text_Only_Rule: 0 (no regex)
        assert len(rules) == 4

    def test_rule_naming(self):
        adapter = YaraAdapter()
        rules = adapter.load(YARA_FIXTURE)
        names = [r["name"] for r in rules]
        assert "Detect_AWS_Key:access_key" in names
        assert "Detect_AWS_Key:secret_key" in names

    def test_modifiers_preserved(self):
        adapter = YaraAdapter()
        rules = adapter.load(YARA_FIXTURE)
        secret_key = next(r for r in rules if r["name"] == "Detect_AWS_Key:secret_key")
        assert "yara_modifiers" in secret_key["metadata"]
        assert "ascii" in secret_key["metadata"]["yara_modifiers"]

    def test_metadata_from_meta_section(self):
        adapter = YaraAdapter()
        rules = adapter.load(YARA_FIXTURE)
        aws = next(r for r in rules if r["name"] == "Detect_AWS_Key:access_key")
        assert aws["metadata"]["author"] == "Security Team"
        assert aws["severity"] == "high"

    def test_text_only_rule_skipped(self):
        adapter = YaraAdapter()
        rules = adapter.load(YARA_FIXTURE)
        names = [r["name"] for r in rules]
        assert not any("Text_Only_Rule" in n for n in names)

    def test_tags_from_rule_header(self):
        adapter = YaraAdapter()
        rules = adapter.load(YARA_FIXTURE)
        aws = next(r for r in rules if r["name"] == "Detect_AWS_Key:access_key")
        assert "credential" in aws["tags"]
        assert "cloud" in aws["tags"]

    def test_load_via_loader(self):
        rules = load_rules(YARA_FIXTURE)
        assert len(rules) == 4

    def test_scan_yara(self):
        from click.testing import CliRunner
        from crossfire.cli import main

        runner = CliRunner()
        result = runner.invoke(main, [
            "scan", YARA_FIXTURE,
            "--format", "summary",
            "--samples", "20",
            "--seed", "42",
            "--skip-invalid",
        ])
        assert result.exit_code == 0


class TestSigmaAdapter:
    def test_can_load(self):
        adapter = SigmaAdapter()
        assert adapter.can_load(SIGMA_FIXTURE)

    def test_cannot_load_semgrep(self):
        adapter = SigmaAdapter()
        # Semgrep has rules: but not detection:/logsource:
        assert not adapter.can_load(SEMGREP_FIXTURE)

    def test_load_rules(self):
        adapter = SigmaAdapter()
        rules = adapter.load(SIGMA_FIXTURE)
        # 3 regex patterns from CommandLine|re list
        assert len(rules) == 3

    def test_field_name_preserved(self):
        adapter = SigmaAdapter()
        rules = adapter.load(SIGMA_FIXTURE)
        for r in rules:
            assert r["metadata"]["sigma_field"] == "CommandLine"

    def test_severity_mapping(self):
        adapter = SigmaAdapter()
        rules = adapter.load(SIGMA_FIXTURE)
        assert rules[0]["severity"] == "high"

    def test_tags(self):
        adapter = SigmaAdapter()
        rules = adapter.load(SIGMA_FIXTURE)
        assert "attack.execution" in rules[0]["tags"]

    def test_load_via_loader(self):
        # Note: Sigma and Semgrep both use YAML. The adapter's can_load
        # content sniffing should differentiate them.
        rules = load_rules(SIGMA_FIXTURE)
        assert len(rules) == 3

    def test_no_regex_patterns(self, tmp_path: Path):
        path = tmp_path / "no_regex.yaml"
        path.write_text("""
title: Simple Rule
detection:
    selection:
        EventID: 4688
    condition: selection
logsource:
    category: process_creation
level: medium
""")
        adapter = SigmaAdapter()
        rules = adapter.load(str(path))
        assert len(rules) == 0


class TestSnortAdapter:
    def test_can_load(self):
        adapter = SnortAdapter()
        assert adapter.can_load(SNORT_FIXTURE)

    def test_cannot_load_non_rules(self, tmp_path: Path):
        path = tmp_path / "test.rules"
        path.write_text("# just a comment\n")
        adapter = SnortAdapter()
        assert not adapter.can_load(str(path))

    def test_load_rules(self):
        adapter = SnortAdapter()
        rules = adapter.load(SNORT_FIXTURE)
        # Rule 1: 1 pcre, Rule 2: 1 pcre, Rule 3: 2 pcre, Rule 4: 0 pcre
        assert len(rules) == 4

    def test_sid_naming(self):
        adapter = SnortAdapter()
        rules = adapter.load(SNORT_FIXTURE)
        names = [r["name"] for r in rules]
        assert "sid:1000001" in names
        assert "sid:1000002" in names
        # Rule 3 has 2 pcre patterns
        assert "sid:1000003_pcre1" in names
        assert "sid:1000003_pcre2" in names

    def test_message_preserved(self):
        adapter = SnortAdapter()
        rules = adapter.load(SNORT_FIXTURE)
        aws = next(r for r in rules if r["name"] == "sid:1000001")
        assert aws["metadata"]["message"] == "Possible AWS Key Exfiltration"

    def test_severity_from_priority(self):
        adapter = SnortAdapter()
        rules = adapter.load(SNORT_FIXTURE)
        by_name = {r["name"]: r for r in rules}
        assert by_name["sid:1000001"]["severity"] == "critical"  # priority:1
        assert by_name["sid:1000002"]["severity"] == "high"  # priority:2

    def test_classtype_in_tags(self):
        adapter = SnortAdapter()
        rules = adapter.load(SNORT_FIXTURE)
        sql = next(r for r in rules if r["name"] == "sid:1000002")
        assert "web-application-attack" in sql["tags"]

    def test_load_via_loader(self):
        rules = load_rules(SNORT_FIXTURE)
        assert len(rules) == 4

    def test_no_pcre_rules_skipped(self, tmp_path: Path):
        path = tmp_path / "no_pcre.rules"
        path.write_text(
            'alert tcp any any -> any any (msg:"Test"; content:"hello"; sid:1;)\n'
        )
        adapter = SnortAdapter()
        # can_load checks for "pcre" in content
        assert not adapter.can_load(str(path))
