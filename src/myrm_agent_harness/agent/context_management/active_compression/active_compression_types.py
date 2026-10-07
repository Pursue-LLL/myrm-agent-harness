"""Type definitions for Active-Turn Live Context Compression and Token Pressure Dashboard.

Provides immutable data contracts for token pressure gauging, trigger origins,
lossless anchor preservation, and active compression results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class TokenPressureLevel(StrEnum):
    """Categorical classification of session context token pressure."""

    NORMAL = "normal"          # < 50%
    MODERATE = "moderate"      # 50% - 75%
    HIGH = "high"              # 75% - 90% (Warning, recommend /compress)
    CRITICAL = "critical"      # >= 90% (Urgent auto-compaction required)


class CompressTriggerKind(StrEnum):
    """Origin trigger source of active compression."""

    USER_EXPLICIT_SLASH = "user_explicit_slash"  # e.g. /compress command
    USER_ONE_CLICK_UI = "user_one_click_ui"      # GUI HUD button click
    PRESSURE_THRESHOLD_AUTO = "pressure_auto"    # Auto probe triggered at high watermark
    PROGRAMMATIC_API = "programmatic_api"        # Developer or test trigger


@dataclass(frozen=True)
class TokenPressureSnapshot:
    """Real-time microsecond token pressure measurement for HUD and decision gates."""

    current_tokens: int
    context_limit: int
    usage_ratio: float
    pressure_level: TokenPressureLevel
    estimated_latency_seconds: float
    recommend_compression: bool
    status_text: str
    measured_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ActiveCompressionConfig:
    """Configuration governing active turn context compaction thresholds."""

    context_limit: int = 128000
    high_watermark_ratio: float = 0.75
    critical_watermark_ratio: float = 0.90
    keep_head_turns: int = 1
    keep_tail_turns: int = 2
    max_summary_tokens: int = 800
    tool_output_compact_threshold_chars: int = 200


@dataclass(frozen=True)
class ActiveCompressionResult:
    """Immutable result emitted upon completing active turn compression."""

    is_compressed: bool
    trigger_kind: CompressTriggerKind
    original_tokens: int
    compacted_tokens: int
    reclaimed_tokens: int
    reclaim_ratio: float
    frozen_head_count: int
    preserved_tail_count: int
    folded_middle_count: int
    compacted_messages: tuple[dict[str, str], ...]
    duration_ms: float
