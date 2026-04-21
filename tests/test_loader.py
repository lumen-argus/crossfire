"""Tests for rule loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crossfire.errors import LoadError, ValidationError
from crossfire.loader import load_multiple, load_rules


class TestLoadJson:
    def test_load_array(self, sample_rules_path: str):
        rules = load_rules(sample_rules_path)
        assert len(rules) == 5
        assert rules[0].name == "aws_access_key"
        assert rules[0].detector == "secrets"

    def test_load_object_with_rules_key(self, tmp_path: Path):
        data = {"rules": [{"name": "test", "pattern": "abc"}]}
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        rules = load_rules(str(path))
        assert len(rules) == 1

    def test_load_with_field_mapping(self, tmp_path: Path):
        data = [{"id": "my_rule", "regex": "[a-z]+"}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        rules = load_rules(str(path), field_mapping={"name": "id", "pattern": "regex"})
        assert rules[0].name == "my_rule"
        assert rules[0].pattern == "[a-z]+"


class TestLoadYaml:
    def test_load_yaml_array(self, tmp_path: Path):
        data = [{"name": "test", "pattern": "abc"}]
        path = tmp_path / "rules.yaml"
        path.write_text(yaml.dump(data))
        rules = load_rules(str(path))
        assert len(rules) == 1

    def test_load_yaml_with_rules_key(self, tmp_path: Path):
        data = {"rules": [{"name": "test", "pattern": "abc"}]}
        path = tmp_path / "rules.yml"
        path.write_text(yaml.dump(data))
        rules = load_rules(str(path))
        assert len(rules) == 1


class TestLoadCsv:
    def test_load_csv(self, tmp_path: Path):
        path = tmp_path / "rules.csv"
        path.write_text("name,pattern,detector\ntest_rule,abc,secrets\n")
        rules = load_rules(str(path))
        assert len(rules) == 1
        assert rules[0].name == "test_rule"
        assert rules[0].detector == "secrets"


class TestFailFastValidation:
    def test_invalid_regex_fails(self, tmp_path: Path):
        data = [{"name": "broken", "pattern": "[a-z(+"}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValidationError, match="invalid regex"):
            load_rules(str(path))

    def test_invalid_regex_with_skip(self, tmp_path: Path):
        data = [
            {"name": "broken", "pattern": "[a-z(+"},
            {"name": "valid", "pattern": "[a-z]+"},
        ]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        rules = load_rules(str(path), skip_invalid=True)
        assert len(rules) == 1
        assert rules[0].name == "valid"

    def test_stdlib_incompatible_pattern_fails(self, tmp_path: Path):
        # Non-leading `(?i)` flags: stdlib `re` rejects on 3.11+. Without RE2
        # the stdlib fallback already caught this; the regression that
        # prompted the fix was that when RE2 is installed, the loader used
        # to accept the pattern and the parallel worker then crashed on
        # stdlib `re.compile`. The companion test below covers that config.
        data = [{"name": "non_leading_flag", "pattern": r"(?i)foo(?i)bar"}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValidationError, match="invalid regex"):
            load_rules(str(path))

    def test_stdlib_incompatible_pattern_with_skip(self, tmp_path: Path):
        data = [
            {"name": "non_leading_flag", "pattern": r"(?i)foo(?i)bar"},
            {"name": "valid", "pattern": "[a-z]+"},
        ]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        rules = load_rules(str(path), skip_invalid=True)
        assert [r.name for r in rules] == ["valid"]

    @pytest.mark.skipif(
        not __import__("crossfire.regex", fromlist=["is_re2_available"]).is_re2_available(),
        reason="RE2 asymmetry is only observable when google-re2 is installed",
    )
    def test_re2_accepted_but_stdlib_rejected_fails_load(self, tmp_path: Path):
        """Regression guard for the original 0.2.2 bug: when google-re2 is
        installed, the loader must still reject patterns that RE2 accepts but
        stdlib `re` cannot compile. Without this test, a revert of the
        stdlib-first validation in `crossfire.regex.compile` would pass the
        default (no-RE2) test suite.
        """
        import re2

        pattern = r"(?i)foo(?i)bar"
        try:
            re2.compile(pattern)
        except Exception as exc:
            pytest.skip(
                f"RE2 no longer accepts {pattern!r} ({exc}); regression guard is "
                f"vacuous — pick a new RE2-accepted / stdlib-rejected pattern."
            )

        data = [{"name": "re2_only", "pattern": pattern}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValidationError, match="invalid regex"):
            load_rules(str(path))

    def test_empty_pattern_fails(self, tmp_path: Path):
        data = [{"name": "empty", "pattern": ""}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValidationError, match="empty pattern"):
            load_rules(str(path))

    def test_whitespace_pattern_fails(self, tmp_path: Path):
        data = [{"name": "spaces", "pattern": "   "}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValidationError, match="empty pattern"):
            load_rules(str(path))

    def test_duplicate_name_fails(self, tmp_path: Path):
        data = [
            {"name": "dupe", "pattern": "abc"},
            {"name": "dupe", "pattern": "def"},
        ]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValidationError, match="Duplicate rule name"):
            load_rules(str(path))

    def test_duplicate_name_with_skip(self, tmp_path: Path):
        data = [
            {"name": "dupe", "pattern": "abc"},
            {"name": "dupe", "pattern": "def"},
        ]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        rules = load_rules(str(path), skip_invalid=True)
        assert len(rules) == 1

    def test_missing_name_fails(self, tmp_path: Path):
        data = [{"pattern": "abc"}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValidationError, match="missing a name"):
            load_rules(str(path))

    def test_missing_pattern_fails(self, tmp_path: Path):
        data = [{"name": "no_pattern"}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValidationError, match="missing a pattern"):
            load_rules(str(path))

    def test_file_not_found(self):
        with pytest.raises(LoadError, match="File not found"):
            load_rules("/nonexistent/path.json")

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.json"
        path.write_text("[]")
        with pytest.raises(LoadError, match="No rules found"):
            load_rules(str(path))

    def test_unsupported_format(self, tmp_path: Path):
        path = tmp_path / "rules.xml"
        path.write_text("<rules/>")
        with pytest.raises(LoadError, match="Unsupported file format"):
            load_rules(str(path))

    def test_non_mapping_entry_fails(self, tmp_path: Path):
        data = ["not_a_dict"]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        with pytest.raises(ValidationError, match="not a mapping"):
            load_rules(str(path))


class TestPriority:
    def test_explicit_priority(self, tmp_path: Path):
        data = [{"name": "test", "pattern": "abc"}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        rules = load_rules(str(path), priority=42)
        assert rules[0].priority == 42

    def test_default_priority(self, sample_rules_path: str):
        rules = load_rules(sample_rules_path)
        assert rules[0].priority == 0


class TestMetadata:
    def test_extra_fields_in_metadata(self, tmp_path: Path):
        data = [{"name": "test", "pattern": "abc", "action": "block", "custom": "value"}]
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(data))
        rules = load_rules(str(path))
        assert rules[0].metadata["action"] == "block"
        assert rules[0].metadata["custom"] == "value"


class TestLoadMultiple:
    def test_load_two_files(self, sample_rules_path: str, disjoint_rules_path: str):
        rules = load_multiple([sample_rules_path, disjoint_rules_path])
        assert len(rules) == 8  # 5 + 3

    def test_priority_ordering(self, tmp_path: Path):
        data_a = [{"name": "rule_a", "pattern": "aaa"}]
        data_b = [{"name": "rule_b", "pattern": "bbb"}]
        path_a = tmp_path / "a.json"
        path_b = tmp_path / "b.json"
        path_a.write_text(json.dumps(data_a))
        path_b.write_text(json.dumps(data_b))

        rules = load_multiple([str(path_a), str(path_b)])
        # First file gets higher default priority
        assert rules[0].priority > rules[1].priority

    def test_explicit_priorities(self, tmp_path: Path):
        data_a = [{"name": "rule_a", "pattern": "aaa"}]
        data_b = [{"name": "rule_b", "pattern": "bbb"}]
        path_a = tmp_path / "a.json"
        path_b = tmp_path / "b.json"
        path_a.write_text(json.dumps(data_a))
        path_b.write_text(json.dumps(data_b))

        rules = load_multiple(
            [str(path_a), str(path_b)],
            priorities={"a.json": 50, "b.json": 100},
        )
        assert rules[0].priority == 50  # a.json
        assert rules[1].priority == 100  # b.json
