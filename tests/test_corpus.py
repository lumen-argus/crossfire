"""Tests for real-world corpus loading and evaluation."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from crossfire.corpus import (
    DiffReport,
    LabeledEntry,
    diff_corpora,
    evaluate_corpus,
    load_corpus_git,
    load_corpus_jsonl,
)
from crossfire.errors import LoadError
from crossfire.models import Rule


def _make_rule(name: str, pattern: str, tags: list[str] | None = None) -> Rule:
    return Rule(
        name=name,
        pattern=pattern,
        compiled=re.compile(pattern),
        tags=tags or [],
    )


class TestLoadCorpusJsonl:
    def test_basic_load(self, tmp_path: Path):
        path = tmp_path / "corpus.jsonl"
        lines = [
            json.dumps({"text": "AKIAIOSFODNN7EXAMPLE", "label": "aws_key"}),
            json.dumps({"text": "xoxb-123-456-abc", "label": "slack_token"}),
        ]
        path.write_text("\n".join(lines))
        entries = load_corpus_jsonl(str(path))
        assert len(entries) == 2
        assert entries[0].text == "AKIAIOSFODNN7EXAMPLE"
        assert entries[0].label == "aws_key"

    def test_custom_field_names(self, tmp_path: Path):
        path = tmp_path / "corpus.jsonl"
        path.write_text(json.dumps({"content": "hello", "type": "test"}) + "\n")
        entries = load_corpus_jsonl(str(path), text_field="content", label_field="type")
        assert entries[0].text == "hello"
        assert entries[0].label == "test"

    def test_unlabeled_entries(self, tmp_path: Path):
        path = tmp_path / "corpus.jsonl"
        path.write_text(json.dumps({"text": "hello world"}) + "\n")
        entries = load_corpus_jsonl(str(path))
        assert entries[0].label == ""

    def test_skips_empty_lines(self, tmp_path: Path):
        path = tmp_path / "corpus.jsonl"
        path.write_text(
            json.dumps({"text": "a"})
            + "\n"
            + "\n"  # empty
            + json.dumps({"text": "b"})
            + "\n"
        )
        entries = load_corpus_jsonl(str(path))
        assert len(entries) == 2

    def test_skips_invalid_json(self, tmp_path: Path):
        path = tmp_path / "corpus.jsonl"
        path.write_text(
            json.dumps({"text": "valid"})
            + "\n"
            + "not json\n"
            + json.dumps({"text": "also valid"})
            + "\n"
        )
        entries = load_corpus_jsonl(str(path))
        assert len(entries) == 2

    def test_file_not_found(self):
        with pytest.raises(LoadError, match="not found"):
            load_corpus_jsonl("/nonexistent/file.jsonl")

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        with pytest.raises(LoadError, match="No valid entries"):
            load_corpus_jsonl(str(path))

    def test_source_field(self, tmp_path: Path):
        path = tmp_path / "corpus.jsonl"
        path.write_text(json.dumps({"text": "hello", "source": "test-1"}) + "\n")
        entries = load_corpus_jsonl(str(path))
        assert entries[0].source == "test-1"


class TestLoadCorpusGit:
    def test_loads_from_git_repo(self, tmp_path: Path):
        # Create a mini git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
        )
        test_file = tmp_path / "secrets.txt"
        test_file.write_text("AKIAIOSFODNN7EXAMPLE\nsome_password=hunter2\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add secrets"],
            cwd=tmp_path,
            capture_output=True,
        )

        entries = load_corpus_git(tmp_path, max_commits=10)
        assert len(entries) > 0
        texts = [e.text for e in entries]
        assert any("AKIA" in t for t in texts)

    def test_not_a_repo(self, tmp_path: Path):
        with pytest.raises(LoadError, match="Not a git repository"):
            load_corpus_git(tmp_path)


class TestEvaluateCorpus:
    def test_basic_evaluation(self):
        rules = [
            _make_rule("digits", r"\d{8}"),
            _make_rule("letters", r"[a-z]{8}"),
        ]
        corpus = [
            LabeledEntry(text="12345678"),
            LabeledEntry(text="abcdefgh"),
            LabeledEntry(text="12ab34cd"),  # matches neither
        ]
        report = evaluate_corpus(rules, corpus)
        assert report.total_entries == 3
        assert report.match_matrix["digits"] == 1
        assert report.match_matrix["letters"] == 1

    def test_co_firing_detection(self):
        rules = [
            _make_rule("broad", r"[a-z0-9]+"),
            _make_rule("specific", r"abc\d+"),
        ]
        corpus = [
            LabeledEntry(text="abc123"),  # matches both
            LabeledEntry(text="xyz789"),  # matches only broad
        ]
        report = evaluate_corpus(rules, corpus)
        assert len(report.co_firing) == 1
        assert report.co_firing[0][2] == 1  # co-fired once

    def test_labeled_evaluation(self):
        rules = [
            _make_rule("aws_key", r"AKIA[A-Z0-9]{16}"),
            _make_rule("slack", r"xoxb-\d+-\d+-\w+"),
        ]
        corpus = [
            LabeledEntry(text="AKIAIOSFODNN7EXAMPLE1", label="aws_key"),
            LabeledEntry(text="xoxb-123-456-abcdef", label="slack"),
            LabeledEntry(text="not_a_secret", label="aws_key"),  # FN for aws_key
        ]
        report = evaluate_corpus(rules, corpus)
        aws_m = next(m for m in report.rule_metrics if m.name == "aws_key")
        assert aws_m.true_positives == 1
        assert aws_m.false_negatives == 1
        assert aws_m.recall == 0.5

    def test_unlabeled_no_metrics(self):
        rules = [_make_rule("test", r"\d+")]
        corpus = [LabeledEntry(text="123")]
        report = evaluate_corpus(rules, corpus)
        assert report.labeled_entries == 0
        m = report.rule_metrics[0]
        assert m.precision == 0.0  # no labels → no precision

    def test_empty_corpus(self):
        rules = [_make_rule("test", r"\d+")]
        report = evaluate_corpus(rules, [])
        assert report.total_entries == 0

    def test_redact_samples(self):
        """redact_samples should not crash (logging behavior only)."""
        rules = [_make_rule("test", r"\d+")]
        corpus = [LabeledEntry(text="123")]
        report = evaluate_corpus(rules, corpus, redact_samples=True)
        assert report.total_entries == 1


class TestDiffCorpora:
    def test_basic_diff(self):
        rules = [
            _make_rule("digits", r"\d{4}"),
            _make_rule("letters", r"[a-z]{4}"),
        ]
        corpus_a = [
            LabeledEntry(text="1234"),
            LabeledEntry(text="5678"),
            LabeledEntry(text="abcd"),
        ]
        corpus_b = [
            LabeledEntry(text="abcd"),
            LabeledEntry(text="efgh"),
            LabeledEntry(text="ijkl"),
        ]
        result = diff_corpora(rules, corpus_a, corpus_b)
        assert isinstance(result, DiffReport)
        assert result.entries_a == 3
        assert result.entries_b == 3

        # digits: 2/3 in A, 0/3 in B → significant drift
        digits_r = next(r for r in result.results if r.rule == "digits")
        assert digits_r.significant is True

    def test_no_drift(self):
        rules = [_make_rule("any", r".+")]
        corpus_a = [LabeledEntry(text="hello")]
        corpus_b = [LabeledEntry(text="world")]
        result = diff_corpora(rules, corpus_a, corpus_b)
        any_r = next(r for r in result.results if r.rule == "any")
        assert any_r.drift == 0.0

    def test_empty_corpora(self):
        rules = [_make_rule("test", r"\d+")]
        result = diff_corpora(rules, [], [])
        assert result.rules_with_matches == 0


class TestEvaluateCli:
    def test_evaluate_command(self, tmp_path: Path, sample_rules_path: str):
        corpus_path = tmp_path / "corpus.jsonl"
        corpus_path.write_text(
            json.dumps({"text": "AKIAIOSFODNN7EXAMPLE1", "label": "aws_access_key"})
            + "\n"
            + json.dumps({"text": "test@example.com"})
            + "\n"
        )

        from click.testing import CliRunner

        from crossfire.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "evaluate",
                sample_rules_path,
                "--corpus",
                str(corpus_path),
                "--format",
                "summary",
            ],
        )
        assert result.exit_code == 0
        assert "Evaluated" in result.output

    def test_diff_command(self, tmp_path: Path, sample_rules_path: str):
        corpus_a = tmp_path / "a.jsonl"
        corpus_b = tmp_path / "b.jsonl"
        corpus_a.write_text(
            json.dumps({"text": "12345678"}) + "\n" + json.dumps({"text": "abcdefgh"}) + "\n"
        )
        corpus_b.write_text(
            json.dumps({"text": "abcdefgh"}) + "\n" + json.dumps({"text": "ijklmnop"}) + "\n"
        )

        from click.testing import CliRunner

        from crossfire.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "diff",
                sample_rules_path,
                "--corpus-a",
                str(corpus_a),
                "--corpus-b",
                str(corpus_b),
            ],
        )
        assert result.exit_code == 0
        assert "Differential Analysis" in result.output
