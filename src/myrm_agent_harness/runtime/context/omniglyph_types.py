"""OmniGlyph multimodal visual context channel and Ultra token governor types.

Defines strict type hints, risk classifications, configuration contracts,
and receipts for rasterized text-to-visual channels and heuristic pruning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskRiskLevel(StrEnum):
    """Risk sensitivity levels for task execution."""

    LOW = "low"  # Read-only docs, historical logs, research background
    MEDIUM = "medium"  # Broad QA, conceptual brain-storming
    HIGH = "high"  # Code refactor, command execution, patch application
    CRITICAL = "critical"  # Financial, auth secrets, legal contracts, destructive mutations


class BypassReason(StrEnum):
    """Explicit justification when visual routing is bypassed."""

    NOT_OPTED_IN = "not_opted_in"
    HIGH_RISK_TASK = "high_risk_task"
    TEXT_BELOW_BREAK_EVEN = "text_below_break_even"
    DISABLED_BY_CONFIG = "disabled_by_config"
    NO_VALID_SEGMENTS = "no_valid_segments"


@dataclass(frozen=True)
class OmniGlyphConfig:
    """Operational settings for the OmniGlyph visual context channel."""

    image_width: int = 1600
    image_height: int = 2400
    font_size: int = 14
    line_spacing: int = 4
    margin: int = 32
    fixed_vlm_token_cost: int = 1600
    break_even_token_threshold: int = 2500
    min_chars_per_glyph: int = 4000
    enabled: bool = True
    opt_in: bool = False
    allowed_risk_levels: tuple[TaskRiskLevel, ...] = (TaskRiskLevel.LOW,)


@dataclass(frozen=True)
class RenderedGlyphPayload:
    """Artifact of a text page rendered into a high-density visual glyph."""

    glyph_id: str
    image_base64: str
    mime_type: str
    text_char_count: int
    estimated_raw_text_tokens: int
    estimated_visual_tokens: int
    saved_tokens: int
    compression_ratio: float
    checksum_sha256: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class UltraFilterScore:
    """Scoring and pruning receipt for a segmented text chunk."""

    segment_id: str
    original_text: str
    information_density: float
    relevance_score: float
    combined_score: float
    keep_decision: bool
    reason: str


@dataclass(frozen=True)
class VisualChannelRoutingResult:
    """Final arbitration result of context channel routing."""

    is_routed_to_visual: bool
    bypassed_reason: BypassReason | None
    rendered_glyphs: tuple[RenderedGlyphPayload, ...]
    retained_text: str
    raw_tokens_before: int
    tokens_after: int
    net_saved_tokens: int
    filter_scores: tuple[UltraFilterScore, ...]
