"""Relationship classification and clustering for rule overlap results."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from crossfire.confidence import wilson_interval
from crossfire.evaluator import MatchMatrix
from crossfire.models import ClusterInfo, OverlapResult, Rule

log = logging.getLogger("crossfire.classifier")


class Classifier:
    """Classifies pairwise rule relationships and clusters overlapping rules."""

    def __init__(
        self,
        threshold: float = 0.8,
        cluster_threshold: float = 0.6,
        overlap_min: float = 0.2,
    ) -> None:
        """Initialize classifier.

        Args:
            threshold: Minimum overlap to classify as duplicate/subset (0.0-1.0).
            cluster_threshold: Minimum Jaccard similarity for clustering.
            overlap_min: Minimum overlap to report as 'overlap' (below this = disjoint).
        """
        self.threshold = threshold
        self.cluster_threshold = cluster_threshold
        self.overlap_min = overlap_min

    def classify(
        self,
        matrix: MatchMatrix,
        rules: list[Rule],
        corpus_sizes: dict[str, int],
    ) -> tuple[list[OverlapResult], list[ClusterInfo]]:
        """Classify all rule pairs and build clusters.

        Args:
            matrix: Match matrix from evaluator.
            rules: List of all rules (for metadata lookup).
            corpus_sizes: Mapping of rule_name → number of positive corpus entries.

        Returns:
            Tuple of (overlap_results, clusters).
        """
        rule_map = {r.name: r for r in rules}
        rule_names = [r.name for r in rules]
        results: list[OverlapResult] = []

        # Evaluate all unique pairs
        for i, name_a in enumerate(rule_names):
            for name_b in rule_names[i + 1:]:
                result = self._classify_pair(
                    name_a, name_b, matrix, rule_map, corpus_sizes
                )
                if result:
                    results.append(result)

        # Count by relationship type
        counts = defaultdict(int)
        for r in results:
            counts[r.relationship] += 1

        log.info(
            "Classification complete: %d duplicates, %d subsets, %d overlaps, %d disjoint",
            counts.get("duplicate", 0),
            counts.get("subset", 0) + counts.get("superset", 0),
            counts.get("overlap", 0),
            counts.get("disjoint", 0),
        )

        # Build clusters from non-disjoint pairs
        clusters = self._build_clusters(results, rule_map)

        return results, clusters

    def _classify_pair(
        self,
        name_a: str,
        name_b: str,
        matrix: MatchMatrix,
        rule_map: dict[str, Rule],
        corpus_sizes: dict[str, int],
    ) -> Optional[OverlapResult]:
        """Classify the relationship between two rules."""
        size_a = corpus_sizes.get(name_a, 0)
        size_b = corpus_sizes.get(name_b, 0)

        if size_a == 0 or size_b == 0:
            return None

        # How many of B's corpus does A match?
        a_matches_b = matrix.get(name_a, {}).get(name_b, 0)
        # How many of A's corpus does B match?
        b_matches_a = matrix.get(name_b, {}).get(name_a, 0)

        overlap_a_to_b = a_matches_b / size_b
        overlap_b_to_a = b_matches_a / size_a

        # Jaccard: intersection / union on combined corpus
        # intersection = strings matched by both
        intersection = min(a_matches_b, b_matches_a)
        union = size_a + size_b - intersection
        jaccard = intersection / union if union > 0 else 0.0

        # Classify relationship
        relationship, recommendation, reason = self._determine_relationship(
            name_a, name_b, overlap_a_to_b, overlap_b_to_a,
            rule_map.get(name_a), rule_map.get(name_b),
        )

        # Skip disjoint pairs (not worth reporting)
        if relationship == "disjoint":
            return None

        log.debug(
            "Pair (%s, %s): a->b=%.0f%%, b->a=%.0f%%, jaccard=%.2f, rel=%s",
            name_a, name_b,
            overlap_a_to_b * 100, overlap_b_to_a * 100,
            jaccard, relationship,
        )

        # Compute confidence intervals
        ci_ab = wilson_interval(a_matches_b, size_b)
        ci_ba = wilson_interval(b_matches_a, size_a)

        # Warn if CI is too wide for reliable classification
        width_ab = round(ci_ab[1] - ci_ab[0], 4)
        width_ba = round(ci_ba[1] - ci_ba[0], 4)
        if width_ab > 0.3 or width_ba > 0.3:
            log.warning(
                "Pair (%s, %s): wide CI (a->b: %.2f, b->a: %.2f) — "
                "increase --samples for more reliable results",
                name_a, name_b, width_ab, width_ba,
            )

        return OverlapResult(
            rule_a=name_a,
            rule_b=name_b,
            source_a=rule_map[name_a].source if name_a in rule_map else "",
            source_b=rule_map[name_b].source if name_b in rule_map else "",
            a_matches_b_corpus=a_matches_b,
            b_matches_a_corpus=b_matches_a,
            a_corpus_size=size_a,
            b_corpus_size=size_b,
            overlap_a_to_b=round(overlap_a_to_b, 4),
            overlap_b_to_a=round(overlap_b_to_a, 4),
            jaccard=round(jaccard, 4),
            relationship=relationship,
            recommendation=recommendation,
            reason=reason,
            ci_a_to_b=ci_ab,
            ci_b_to_a=ci_ba,
        )

    def _determine_relationship(
        self,
        name_a: str,
        name_b: str,
        overlap_a_to_b: float,
        overlap_b_to_a: float,
        rule_a: Optional[Rule],
        rule_b: Optional[Rule],
    ) -> tuple[str, str, str]:
        """Determine relationship type, recommendation, and reason."""
        T = self.threshold

        if overlap_a_to_b >= T and overlap_b_to_a >= T:
            relationship = "duplicate"
            rec, reason = self._recommend_keep(name_a, name_b, rule_a, rule_b)
            return relationship, rec, reason

        if overlap_a_to_b >= T and overlap_b_to_a < T:
            # A matches most of B's corpus, but B doesn't match most of A's
            # → B is a subset of A (A is more comprehensive)
            relationship = "subset"
            priority_a = rule_a.priority if rule_a else 0
            priority_b = rule_b.priority if rule_b else 0
            if priority_b > priority_a:
                return relationship, "keep_both", f"'{name_b}' has higher priority but is a subset"
            return relationship, "keep_a", f"'{name_a}' is more comprehensive (superset)"

        if overlap_b_to_a >= T and overlap_a_to_b < T:
            relationship = "superset"
            priority_a = rule_a.priority if rule_a else 0
            priority_b = rule_b.priority if rule_b else 0
            if priority_a > priority_b:
                return relationship, "keep_both", f"'{name_a}' has higher priority but is a subset"
            return relationship, "keep_b", f"'{name_b}' is more comprehensive (superset)"

        if overlap_a_to_b >= self.overlap_min or overlap_b_to_a >= self.overlap_min:
            return "overlap", "review", "Partial overlap — review manually"

        return "disjoint", "keep_both", ""

    def _recommend_keep(
        self,
        name_a: str,
        name_b: str,
        rule_a: Optional[Rule],
        rule_b: Optional[Rule],
    ) -> tuple[str, str]:
        """For duplicates, recommend which rule to keep based on priority."""
        priority_a = rule_a.priority if rule_a else 0
        priority_b = rule_b.priority if rule_b else 0

        if priority_a > priority_b:
            source = f" ({rule_a.source})" if rule_a and rule_a.source else ""
            return "keep_a", f"Higher priority source{source}"
        if priority_b > priority_a:
            source = f" ({rule_b.source})" if rule_b and rule_b.source else ""
            return "keep_b", f"Higher priority source{source}"
        return "review", "Equal priority — review manually"

    def _build_clusters(
        self,
        results: list[OverlapResult],
        rule_map: dict[str, Rule],
    ) -> list[ClusterInfo]:
        """Build clusters of overlapping rules using connected components."""
        # Build adjacency graph for non-disjoint pairs above cluster threshold
        adjacency: dict[str, set[str]] = defaultdict(set)
        for r in results:
            if r.jaccard >= self.cluster_threshold:
                adjacency[r.rule_a].add(r.rule_b)
                adjacency[r.rule_b].add(r.rule_a)

        # Find connected components via BFS
        visited: set[str] = set()
        clusters: list[ClusterInfo] = []
        cluster_id = 0

        for node in adjacency:
            if node in visited:
                continue
            cluster_id += 1
            component: list[str] = []
            queue = [node]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                component.append(current)
                for neighbor in adjacency[current]:
                    if neighbor not in visited:
                        queue.append(neighbor)

            if len(component) < 2:
                continue

            # Rank by priority, pick the highest as "keep"
            component.sort(
                key=lambda n: rule_map[n].priority if n in rule_map else 0,
                reverse=True,
            )
            keep = component[0]
            keep_rule = rule_map.get(keep)
            reason = f"Highest priority in cluster"
            if keep_rule and keep_rule.source:
                reason += f" (from {keep_rule.source})"

            if len(component) > 5:
                log.warning(
                    "Large cluster of %d rules detected — may indicate "
                    "overly broad pattern: %s",
                    len(component),
                    ", ".join(component[:5]) + "...",
                )

            clusters.append(ClusterInfo(
                id=cluster_id,
                rules=component,
                keep=keep,
                reason=reason,
            ))

        if clusters:
            log.info("Built %d clusters from overlapping rules", len(clusters))

        return clusters
