"""Tests for corpus generation."""

from __future__ import annotations

import re

import pytest

from crossfire.errors import GenerationError
from crossfire.generator import CorpusGenerator
from crossfire.models import Rule


def _make_rule(name: str, pattern: str) -> Rule:
    return Rule(name=name, pattern=pattern, compiled=re.compile(pattern))


class TestPositiveGeneration:
    def test_generates_matching_strings(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=0, seed=42)
        rule = _make_rule("digits", r"\d{8}")
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) >= 10
        for e in positive:
            assert rule.compiled.search(e.text), f"'{e.text}' should match {rule.pattern}"

    def test_generates_requested_count(self):
        gen = CorpusGenerator(samples_per_rule=30, negative_samples=0, seed=42)
        rule = _make_rule("hex", r"[0-9a-f]{16}")
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) == 30

    def test_all_entries_linked_to_source(self):
        gen = CorpusGenerator(samples_per_rule=10, negative_samples=5, seed=42)
        rule = _make_rule("test", r"[a-z]{10}")
        entries = gen.generate([rule])
        for e in entries:
            assert e.source_rule == "test"

    def test_respects_max_length(self):
        gen = CorpusGenerator(
            samples_per_rule=20, negative_samples=0,
            max_string_length=32, seed=42,
        )
        rule = _make_rule("long", r"[a-zA-Z0-9]{10,100}")
        entries = gen.generate([rule])
        for e in entries:
            assert len(e.text) <= 32

    def test_deduplicates_within_rule(self):
        gen = CorpusGenerator(samples_per_rule=50, negative_samples=0, seed=42)
        rule = _make_rule("hex", r"[0-9a-f]{16}")
        entries = gen.generate([rule])
        texts = [e.text for e in entries if not e.is_negative]
        # All entries should be unique (set removes duplicates)
        assert len(set(texts)) == len(texts)


class TestNegativeGeneration:
    def test_generates_negatives(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=10, seed=42)
        rule = _make_rule("digits", r"^\d{8}$")
        entries = gen.generate([rule])
        negatives = [e for e in entries if e.is_negative]
        assert len(negatives) > 0
        for e in negatives:
            assert not rule.compiled.search(e.text), \
                f"Negative '{e.text}' should NOT match {rule.pattern}"

    def test_no_negatives_when_zero(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=0, seed=42)
        rule = _make_rule("test", r"\d{4}")
        entries = gen.generate([rule])
        negatives = [e for e in entries if e.is_negative]
        assert len(negatives) == 0


class TestMultipleRules:
    def test_generates_for_all_rules(self):
        gen = CorpusGenerator(samples_per_rule=10, negative_samples=0, seed=42)
        rules = [
            _make_rule("rule_a", r"[a-z]{10}"),
            _make_rule("rule_b", r"\d{10}"),
            _make_rule("rule_c", r"[A-Z]{5}-\d{5}"),
        ]
        entries = gen.generate(rules)
        sources = {e.source_rule for e in entries}
        assert sources == {"rule_a", "rule_b", "rule_c"}

    def test_entries_per_rule(self):
        gen = CorpusGenerator(samples_per_rule=15, negative_samples=5, seed=42)
        rules = [
            _make_rule("a", r"[a-z]{10}"),
            _make_rule("b", r"\d{10}"),
        ]
        entries = gen.generate(rules)
        for rule_name in ("a", "b"):
            positive = [e for e in entries if e.source_rule == rule_name and not e.is_negative]
            assert len(positive) >= 10


class TestFailFast:
    def test_generation_failure_raises(self):
        gen = CorpusGenerator(
            samples_per_rule=50,
            min_valid_samples=50,  # impossible for simple pattern
            negative_samples=0,
            generation_timeout_s=0.5,
            seed=42,
        )
        # Pattern that generates only 1 unique string
        rule = _make_rule("single", r"^exact_match_only$")
        with pytest.raises(GenerationError, match="only .* valid samples"):
            gen.generate([rule])

    def test_generation_failure_skip(self):
        gen = CorpusGenerator(
            samples_per_rule=50,
            min_valid_samples=50,
            negative_samples=0,
            generation_timeout_s=0.5,
            seed=42,
        )
        rule = _make_rule("single", r"^exact_match_only$")
        entries = gen.generate([rule], skip_invalid=True)
        assert len(entries) == 0


class TestReproducibility:
    def test_same_seed_same_output(self):
        rule = _make_rule("test", r"[a-z]{10}")

        gen1 = CorpusGenerator(samples_per_rule=20, negative_samples=5, seed=42)
        entries1 = gen1.generate([rule])

        gen2 = CorpusGenerator(samples_per_rule=20, negative_samples=5, seed=42)
        entries2 = gen2.generate([rule])

        texts1 = [e.text for e in entries1]
        texts2 = [e.text for e in entries2]
        assert texts1 == texts2


class TestEdgeCases:
    def test_anchored_pattern(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=0, seed=42)
        rule = _make_rule("anchored", r"^prefix_[a-z]{5}$")
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) >= 10
        for e in positive:
            assert rule.compiled.search(e.text)

    def test_unicode_pattern(self):
        gen = CorpusGenerator(samples_per_rule=15, negative_samples=0, seed=42,
                              min_valid_samples=5)
        rule = _make_rule("unicode", r"[a-zA-Z0-9]{10}")
        entries = gen.generate([rule])
        assert len([e for e in entries if not e.is_negative]) >= 5

    def test_alternation_pattern(self):
        gen = CorpusGenerator(samples_per_rule=20, negative_samples=0, seed=42)
        rule = _make_rule("alt", r"(foo|bar|baz)_\d{3}")
        entries = gen.generate([rule])
        positive = [e for e in entries if not e.is_negative]
        assert len(positive) >= 3  # at least 3 variants
