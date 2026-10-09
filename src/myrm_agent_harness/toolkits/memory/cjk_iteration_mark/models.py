"""Domain models for CJK ideographic iteration mark disambiguation and recall.

Provides immutable data structures representing CJK run expansions,
three-dimensional token sets (raw, normalized, anchor), and recall match scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DisambiguatedCjkTokens:
    """Three-dimensional token matrix derived from CJK text containing iteration marks."""

    raw_tokens: tuple[str, ...] = field(default_factory=tuple)
    normalized_tokens: tuple[str, ...] = field(default_factory=tuple)
    anchor_tokens: tuple[str, ...] = field(default_factory=tuple)

    @property
    def all_tokens(self) -> set[str]:
        """Union of all valid token representations for recall index lookup."""
        return set(self.raw_tokens) | set(self.normalized_tokens) | set(self.anchor_tokens)


@dataclass(frozen=True)
class IterationMarkRun:
    """A contiguous CJK character run and its iteration-mark expansion."""

    raw_run: str
    expanded_run: str
    expanded_indices: tuple[int, ...]
    raw_bigrams: tuple[str, ...]
    normalized_bigrams: tuple[str, ...]
    anchor_bigrams: tuple[str, ...]


@dataclass(frozen=True)
class IterationExpansionResult:
    """Outcome of resolving ideographic iteration marks across full text."""

    original_text: str
    normalized_text: str
    has_iteration_mark: bool
    marks_expanded_count: int
    runs: tuple[IterationMarkRun, ...]
    tokens: DisambiguatedCjkTokens


@dataclass(frozen=True)
class CjkRecallMatchScore:
    """Match verdict and similarity scoring for CJK iteration mark recall."""

    query: str
    target: str
    is_matched: bool
    raw_overlap_count: int
    normalized_overlap_count: int
    anchor_overlap_count: int
    composite_score: float
    matched_tokens: tuple[str, ...]
