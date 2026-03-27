"""Tests for relationship classification and clustering."""

from __future__ import annotations

import re

from crossfire.classifier import Classifier
from crossfire.models import Recommendation, Relationship, Rule


def _make_rule(name: str, source: str = "test", priority: int = 0) -> Rule:
    return Rule(
        name=name,
        pattern=".",
        compiled=re.compile("."),
        source=source,
        priority=priority,
    )


class TestRelationshipClassification:
    def test_duplicate(self):
        """Both rules match >80% of each other's corpus → duplicate."""
        classifier = Classifier(threshold=0.8)
        rules = [_make_rule("a", priority=10), _make_rule("b", priority=5)]
        matrix = {
            "a": {"a": 50, "b": 45},  # a matches 45/50 of b's corpus
            "b": {"a": 42, "b": 50},  # b matches 42/50 of a's corpus
        }
        sizes = {"a": 50, "b": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        dups = [r for r in results if r.relationship == Relationship.DUPLICATE]
        assert len(dups) == 1
        assert dups[0].recommendation == Recommendation.KEEP_A  # higher priority

    def test_subset(self):
        """A matches most of B's corpus, but B doesn't match most of A's → subset."""
        classifier = Classifier(threshold=0.8)
        rules = [_make_rule("broad"), _make_rule("specific")]
        matrix = {
            "broad": {"broad": 50, "specific": 48},  # broad matches 96% of specific
            "specific": {"broad": 10, "specific": 50},  # specific matches 20% of broad
        }
        sizes = {"broad": 50, "specific": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        subs = [r for r in results if r.relationship == Relationship.SUBSET]
        assert len(subs) == 1
        assert subs[0].recommendation == Recommendation.KEEP_A  # broad is the superset

    def test_superset(self):
        """B matches most of A's corpus, but A doesn't match most of B's → superset."""
        classifier = Classifier(threshold=0.8)
        rules = [_make_rule("specific"), _make_rule("broad")]
        matrix = {
            "specific": {"specific": 50, "broad": 10},
            "broad": {"specific": 48, "broad": 50},
        }
        sizes = {"specific": 50, "broad": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        sups = [r for r in results if r.relationship == Relationship.SUPERSET]
        assert len(sups) == 1
        assert sups[0].recommendation == Recommendation.KEEP_B

    def test_overlap(self):
        """Partial overlap above minimum but below threshold."""
        classifier = Classifier(threshold=0.8, overlap_min=0.2)
        rules = [_make_rule("a"), _make_rule("b")]
        matrix = {
            "a": {"a": 50, "b": 20},  # 40% of b
            "b": {"a": 15, "b": 50},  # 30% of a
        }
        sizes = {"a": 50, "b": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        overlaps = [r for r in results if r.relationship == Relationship.OVERLAP]
        assert len(overlaps) == 1
        assert overlaps[0].recommendation == Recommendation.REVIEW

    def test_disjoint(self):
        """Very low overlap → disjoint (not reported)."""
        classifier = Classifier(threshold=0.8, overlap_min=0.2)
        rules = [_make_rule("a"), _make_rule("b")]
        matrix = {
            "a": {"a": 50, "b": 2},
            "b": {"a": 1, "b": 50},
        }
        sizes = {"a": 50, "b": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        # Disjoint pairs are not reported
        assert len(results) == 0


class TestThresholdBoundary:
    def test_at_exact_threshold(self):
        """At exactly the threshold → classified as duplicate."""
        classifier = Classifier(threshold=0.8)
        rules = [_make_rule("a"), _make_rule("b")]
        matrix = {
            "a": {"a": 50, "b": 40},  # exactly 0.8
            "b": {"a": 40, "b": 50},  # exactly 0.8
        }
        sizes = {"a": 50, "b": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        dups = [r for r in results if r.relationship == Relationship.DUPLICATE]
        assert len(dups) == 1

    def test_just_below_threshold(self):
        """Just below threshold → not duplicate."""
        classifier = Classifier(threshold=0.8)
        rules = [_make_rule("a"), _make_rule("b")]
        matrix = {
            "a": {"a": 50, "b": 39},  # 0.78
            "b": {"a": 39, "b": 50},  # 0.78
        }
        sizes = {"a": 50, "b": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        dups = [r for r in results if r.relationship == Relationship.DUPLICATE]
        assert len(dups) == 0

    def test_custom_threshold(self):
        classifier = Classifier(threshold=0.5)
        rules = [_make_rule("a"), _make_rule("b")]
        matrix = {
            "a": {"a": 50, "b": 30},  # 0.6 >= 0.5
            "b": {"a": 30, "b": 50},  # 0.6 >= 0.5
        }
        sizes = {"a": 50, "b": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        dups = [r for r in results if r.relationship == Relationship.DUPLICATE]
        assert len(dups) == 1


class TestJaccard:
    def test_perfect_overlap(self):
        classifier = Classifier(threshold=0.8)
        rules = [_make_rule("a"), _make_rule("b")]
        matrix = {
            "a": {"a": 50, "b": 50},
            "b": {"a": 50, "b": 50},
        }
        sizes = {"a": 50, "b": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        assert len(results) == 1
        assert results[0].jaccard == 1.0

    def test_zero_overlap(self):
        classifier = Classifier(threshold=0.8, overlap_min=0.2)
        rules = [_make_rule("a"), _make_rule("b")]
        matrix = {
            "a": {"a": 50},
            "b": {"b": 50},
        }
        sizes = {"a": 50, "b": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        # No cross-matches → disjoint (not reported)
        assert len(results) == 0


class TestClustering:
    def test_single_cluster(self):
        """Three mutually overlapping rules should form one cluster."""
        classifier = Classifier(threshold=0.8, cluster_threshold=0.5)
        rules = [
            _make_rule("a", priority=30),
            _make_rule("b", priority=20),
            _make_rule("c", priority=10),
        ]
        # All pairs are duplicates
        matrix = {
            "a": {"a": 50, "b": 45, "c": 45},
            "b": {"a": 45, "b": 50, "c": 45},
            "c": {"a": 45, "b": 45, "c": 50},
        }
        sizes = {"a": 50, "b": 50, "c": 50}
        _, clusters = classifier.classify(matrix, rules, sizes)
        assert len(clusters) == 1
        assert set(clusters[0].rules) == {"a", "b", "c"}
        assert clusters[0].keep == "a"  # highest priority

    def test_two_clusters(self):
        """Two separate groups should form two clusters."""
        classifier = Classifier(threshold=0.8, cluster_threshold=0.5)
        rules = [
            _make_rule("a1", priority=20),
            _make_rule("a2", priority=10),
            _make_rule("b1", priority=20),
            _make_rule("b2", priority=10),
        ]
        # a1-a2 are duplicates, b1-b2 are duplicates, no cross-group overlap
        matrix = {
            "a1": {"a1": 50, "a2": 45},
            "a2": {"a1": 45, "a2": 50},
            "b1": {"b1": 50, "b2": 45},
            "b2": {"b1": 45, "b2": 50},
        }
        sizes = {"a1": 50, "a2": 50, "b1": 50, "b2": 50}
        _, clusters = classifier.classify(matrix, rules, sizes)
        assert len(clusters) == 2

    def test_no_clusters_when_disjoint(self):
        classifier = Classifier(threshold=0.8)
        rules = [_make_rule("a"), _make_rule("b")]
        matrix = {"a": {"a": 50}, "b": {"b": 50}}
        sizes = {"a": 50, "b": 50}
        _, clusters = classifier.classify(matrix, rules, sizes)
        assert len(clusters) == 0


class TestRecommendation:
    def test_higher_priority_kept(self):
        classifier = Classifier(threshold=0.8)
        rules = [
            _make_rule("community", source="community.json", priority=100),
            _make_rule("pro", source="pro.json", priority=50),
        ]
        matrix = {
            "community": {"community": 50, "pro": 48},
            "pro": {"community": 48, "pro": 50},
        }
        sizes = {"community": 50, "pro": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        assert results[0].recommendation == Recommendation.KEEP_A
        assert "community.json" in results[0].reason

    def test_equal_priority_review(self):
        classifier = Classifier(threshold=0.8)
        rules = [_make_rule("a", priority=10), _make_rule("b", priority=10)]
        matrix = {
            "a": {"a": 50, "b": 48},
            "b": {"a": 48, "b": 50},
        }
        sizes = {"a": 50, "b": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        assert results[0].recommendation == Recommendation.REVIEW

    def test_subset_keeps_superset(self):
        classifier = Classifier(threshold=0.8)
        rules = [
            _make_rule("broad", priority=10),
            _make_rule("specific", priority=10),
        ]
        matrix = {
            "broad": {"broad": 50, "specific": 48},
            "specific": {"broad": 10, "specific": 50},
        }
        sizes = {"broad": 50, "specific": 50}
        results, _ = classifier.classify(matrix, rules, sizes)
        subs = [r for r in results if r.relationship == Relationship.SUBSET]
        assert len(subs) == 1
        assert subs[0].recommendation == Recommendation.KEEP_A  # broad is the superset


class TestEmptyInputs:
    def test_no_rules(self):
        classifier = Classifier()
        results, clusters = classifier.classify({}, [], {})
        assert results == []
        assert clusters == []

    def test_single_rule(self):
        classifier = Classifier()
        rules = [_make_rule("only")]
        matrix = {"only": {"only": 50}}
        sizes = {"only": 50}
        results, clusters = classifier.classify(matrix, rules, sizes)
        assert results == []  # no pairs
        assert clusters == []

    def test_zero_corpus(self):
        classifier = Classifier()
        rules = [_make_rule("a"), _make_rule("b")]
        results, _clusters = classifier.classify({}, rules, {"a": 0, "b": 0})
        assert results == []
