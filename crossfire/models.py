"""Data models for Crossfire analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class CompiledPattern(Protocol):
    """Protocol for compiled regex — matches both re.Pattern and re2.Pattern."""

    def search(self, string: str, pos: int = ..., endpos: int = ...) -> object: ...
    def match(self, string: str, pos: int = ..., endpos: int = ...) -> object: ...


class Relationship(StrEnum):
    """Classification of how two rules relate."""

    DUPLICATE = "duplicate"
    SUBSET = "subset"
    SUPERSET = "superset"
    OVERLAP = "overlap"
    DISJOINT = "disjoint"


class Recommendation(StrEnum):
    """Recommended action for an overlapping pair."""

    KEEP_A = "keep_a"
    KEEP_B = "keep_b"
    KEEP_BOTH = "keep_both"
    REVIEW = "review"


@dataclass
class Rule:
    """A single detection rule with a regex pattern."""

    name: str
    pattern: str
    compiled: CompiledPattern
    source: str = ""
    detector: str = ""
    severity: str = ""
    tags: list[str] = field(default_factory=list)
    priority: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class CorpusEntry:
    """A generated test string linked to its source rule."""

    text: str
    source_rule: str
    is_negative: bool = False


@dataclass
class OverlapResult:
    """Overlap measurement between two rules."""

    rule_a: str
    rule_b: str
    source_a: str
    source_b: str
    a_matches_b_corpus: int
    b_matches_a_corpus: int
    a_corpus_size: int
    b_corpus_size: int
    overlap_a_to_b: float
    overlap_b_to_a: float
    jaccard: float
    relationship: Relationship
    recommendation: Recommendation
    reason: str = ""
    ci_a_to_b: tuple[float, float] | None = None  # 95% CI for overlap_a_to_b
    ci_b_to_a: tuple[float, float] | None = None  # 95% CI for overlap_b_to_a


@dataclass
class ClusterInfo:
    """A group of mutually overlapping rules."""

    id: int
    rules: list[str]
    keep: str
    reason: str


@dataclass
class AnalysisReport:
    """Full analysis result."""

    crossfire_version: str
    timestamp: str
    config: dict[str, object]
    input_summary: dict[str, object]
    corpus_summary: dict[str, object]
    evaluation_summary: dict[str, object]
    duplicates: list[OverlapResult]
    subsets: list[OverlapResult]
    overlaps: list[OverlapResult]
    clusters: list[ClusterInfo]
    quality: dict[str, object] | None = None  # Phase 2: quality assessment summary
    summary: dict[str, object] = field(default_factory=dict)
