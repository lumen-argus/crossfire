"""Main analysis orchestrator — coordinates the full pipeline."""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import UTC, datetime

import crossfire
from crossfire.classifier import Classifier
from crossfire.evaluator import Evaluator
from crossfire.generator import CorpusGenerator
from crossfire.loader import load_multiple
from crossfire.models import AnalysisReport, Recommendation, Relationship

log = logging.getLogger("crossfire.analyzer")


def analyze(
    paths: list[str],
    *,
    threshold: float = 0.8,
    cluster_threshold: float = 0.6,
    samples_per_rule: int = 50,
    negative_samples: int = 10,
    max_string_length: int = 256,
    generation_timeout_s: float = 2.0,
    seed: int | None = None,
    workers: int = 0,
    partition_by: str | None = None,
    skip_invalid: bool = False,
    priorities: dict[str, int] | None = None,
    field_mapping: dict[str, str] | None = None,
) -> AnalysisReport:
    """Run the full analysis pipeline.

    Steps:
        1. Load rules from files
        2. Validate (fail-fast unless skip_invalid)
        3. Generate corpus
        4. Cross-evaluate
        5. Classify relationships
        6. Build report

    Args:
        paths: List of rule file paths.
        threshold: Overlap threshold for duplicate/subset classification.
        cluster_threshold: Jaccard threshold for clustering.
        samples_per_rule: Number of corpus strings per rule.
        negative_samples: Number of near-miss strings per rule.
        max_string_length: Maximum generated string length.
        generation_timeout_s: Per-rule generation timeout.
        seed: Random seed for reproducibility.
        workers: Parallel evaluation workers (0 = auto).
        partition_by: Field to partition rules by.
        skip_invalid: Skip invalid rules instead of failing.
        priorities: Mapping of filename → priority.
        field_mapping: Custom field name mapping.

    Returns:
        AnalysisReport with full results.
    """
    t0 = time.monotonic()
    log.info("Analysis started: %d file(s)", len(paths))

    # Step 1-2: Load and validate
    rules = load_multiple(
        paths,
        skip_invalid=skip_invalid,
        priorities=priorities,
        field_mapping=field_mapping,
    )

    # Step 3: Generate corpus
    gen_t0 = time.monotonic()
    generator = CorpusGenerator(
        samples_per_rule=samples_per_rule,
        negative_samples=negative_samples,
        max_string_length=max_string_length,
        generation_timeout_s=generation_timeout_s,
        seed=seed,
    )
    corpus = generator.generate(rules, skip_invalid=skip_invalid)
    gen_duration = time.monotonic() - gen_t0

    # Compute corpus sizes per rule (positive only)
    corpus_sizes: dict[str, int] = Counter(e.source_rule for e in corpus if not e.is_negative)

    # Step 4: Cross-evaluate
    eval_t0 = time.monotonic()
    evaluator = Evaluator(workers=workers, partition_by=partition_by)
    matrix = evaluator.evaluate(rules, corpus)
    eval_duration = time.monotonic() - eval_t0

    # Step 5: Classify
    classifier = Classifier(
        threshold=threshold,
        cluster_threshold=cluster_threshold,
    )
    results, clusters = classifier.classify(matrix, rules, corpus_sizes)

    # Step 5b: Quality assessment
    from crossfire.quality import assess_quality

    quality_report = assess_quality(
        rules,
        corpus,
        matrix,
        corpus_sizes,
        seed=seed,
    )

    # Step 6: Build report
    duplicates = [r for r in results if r.relationship == Relationship.DUPLICATE]
    subsets = [r for r in results if r.relationship in (Relationship.SUBSET, Relationship.SUPERSET)]
    overlaps = [r for r in results if r.relationship == Relationship.OVERLAP]

    # Count recommendations
    all_non_disjoint = duplicates + subsets + overlaps
    drop_count = sum(
        1
        for r in all_non_disjoint
        if r.recommendation in (Recommendation.KEEP_A, Recommendation.KEEP_B)
    )
    review_count = sum(1 for r in all_non_disjoint if r.recommendation == Recommendation.REVIEW)

    total_duration = time.monotonic() - t0

    rules_by_source: dict[str, int] = Counter(r.source for r in rules)

    report = AnalysisReport(
        crossfire_version=crossfire.__version__,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        config={
            "threshold": threshold,
            "cluster_threshold": cluster_threshold,
            "samples_per_rule": samples_per_rule,
            "negative_samples": negative_samples,
            "seed": seed,
            "workers": workers,
            "partition_by": partition_by,
        },
        input_summary={
            "files": paths,
            "total_rules": len(rules),
            "rules_by_source": dict(rules_by_source),
            "rules_skipped": 0,
            "skip_reasons": {},
        },
        corpus_summary={
            "total_strings": len(corpus),
            "positive_strings": sum(1 for e in corpus if not e.is_negative),
            "negative_strings": sum(1 for e in corpus if e.is_negative),
            "generation_duration_s": round(gen_duration, 1),
        },
        evaluation_summary={
            "total_comparisons": len(rules) * sum(1 for e in corpus if not e.is_negative),
            "positive_matches": sum(
                count for rule_counts in matrix.values() for count in rule_counts.values()
            ),
            "duration_s": round(eval_duration, 1),
            "workers": workers or "auto",
        },
        duplicates=duplicates,
        subsets=subsets,
        overlaps=overlaps,
        clusters=clusters,
        quality={
            "broad_patterns": [
                {"name": r.name, "source": r.source, "overlap_count": r.overlap_count}
                for r in quality_report.broad_patterns
            ],
            "low_specificity": [
                {"name": r.name, "source": r.source, "specificity": r.specificity}
                for r in quality_report.low_specificity
            ],
            "fully_redundant": [
                {"name": r.name, "source": r.source} for r in quality_report.fully_redundant
            ],
            "summary": quality_report.summary,
        },
        summary={
            "duplicate_pairs": len(duplicates),
            "subset_pairs": len(subsets),
            "overlap_pairs": len(overlaps),
            "clusters": len(clusters),
            "rules_recommended_drop": drop_count,
            "rules_recommended_review": review_count,
            "broad_patterns": len(quality_report.broad_patterns),
            "low_specificity_rules": len(quality_report.low_specificity),
            "fully_redundant_rules": len(quality_report.fully_redundant),
            "analysis_duration_s": round(total_duration, 1),
        },
    )

    log.info(
        "Analysis complete in %.1fs: %d duplicates, %d subsets, %d overlaps, %d clusters",
        total_duration,
        len(duplicates),
        len(subsets),
        len(overlaps),
        len(clusters),
    )

    return report
