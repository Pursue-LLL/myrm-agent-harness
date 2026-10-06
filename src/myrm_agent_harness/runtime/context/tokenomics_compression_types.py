"""Strongly typed data contracts for the Four-Tier Tokenomics context compression engine.

Provides enums, protected pattern models, budget decisions, and four-dimensional
evaluation metrics with zero Any.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CompressionTierKind(StrEnum):
    """The four progressive tiers of Tokenomics context compression."""

    TIER_1_LOSSLESS_CLEAN = "tier_1_lossless_clean"  # Whitespace normalization, Headroom tabular JSON, URL trims
    TIER_2_STRUCTURAL_DEDUP = "tier_2_structural_dedup"  # Content-hash addressing, CCR retrieval markers
    TIER_3_SEMANTIC_PRUNING = "tier_3_semantic_pruning"  # Relevance filtering, Caveman prose trims, aging decay
    TIER_4_EXTREME_COMPACTION = "tier_4_extreme_compaction"  # Ultra aggressive pruning, atomic statements only


class ContextTaxonomyKind(StrEnum):
    """Classification of context messages for selective compression."""

    USER_CORE_DIRECTIVE = "user_core_directive"  # Zero compression allowed (immutable)
    TASK_STATE = "task_state"  # Structural summaries, checkpoints
    TOOL_EVIDENCE = "tool_evidence"  # Command-aware trimming, diagnosis windows
    BACKGROUND_NOISE = "background_noise"  # Discardable conversation filler, greetings


class TaskRiskLevel(StrEnum):
    """Risk tier of the current task affecting compression aggressiveness."""

    HIGH = "high"  # Core refactoring, financial/security logic; requires strict protected patterns
    LOW = "low"  # Exploratory lookup, documentation drafting, read-only search


class ProtectedPatternKind(StrEnum):
    """Categories of engineering facts shielded from semantic mutation."""

    FILE_PATH = "file_path"
    LINE_NUMBER = "line_number"
    VERSION = "version"
    COMMAND = "command"
    ERROR_CODE = "error_code"
    USER_REQUIREMENT = "user_requirement"


@dataclass(frozen=True)
class ProtectedPatternsConfig:
    """Configuration for protecting non-negotiable engineering facts."""

    code_safe: bool = True
    protect_file_paths: bool = True
    protect_line_numbers: bool = True
    protect_commands: bool = True
    protect_error_codes: bool = True
    custom_protected_terms: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CompressionBudgetDecision:
    """Outcome of dynamic budget routing based on task risk and remaining tokens."""

    selected_tiers: tuple[CompressionTierKind, ...]
    current_tokens: int
    token_budget: int
    watermark_ratio: float
    task_risk: TaskRiskLevel
    rationale: str


@dataclass(frozen=True)
class FourDimensionalMetrics:
    """Four-dimensional quality and balance evaluation metric."""

    token_reduction_rate: float  # Percentage of tokens eliminated (e.g. 0.45 = 45%)
    task_success_rate: float  # Empirical success rate under this compression level
    error_recovery_rate: float  # Rate of self-healing when execution errors occur
    user_rework_rate: float  # Frequency of human user intervening to fix hallucinations


@dataclass(frozen=True)
class TieredCompressionResult:
    """Detailed outcome of executing the compression pipeline."""

    original_tokens_est: int
    compressed_tokens_est: int
    reduction_ratio: float
    tiers_applied: tuple[CompressionTierKind, ...]
    processed_text: str
    protected_spans_preserved: int
