"""Strongly-typed contracts for anti-amnesia compression fallback guard and adaptive turn watchdog.

[INPUT]
- None (pure domain models)

[OUTPUT]
- CompressionFallbackTier: Enum of compression fallback escalation tiers.
- ModelWindowSpec: Specification of context window limits for a compression model.
- CapacityAssertionResult: Detailed outcome of physical window capacity assertion.
- ChunkedSummaryNode: Metadata and text for intermediate map-reduce summary chunk.
- CompressionTransparencyHudState: Frontend-facing transparency badge for compression state.
- TurnBudgetWatchdogState: Runtime state of the adaptive 500-turn watchdog.
- AntiAmnesiaExecutionReport: Unified audit report of compression safety and fidelity.

[POS]
Domain data structures protecting context compression against silent fallback truncation,
preventing catastrophic amnesia, and providing dynamic 500-turn iteration watchdog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CompressionFallbackTier(str, Enum):
    """Escalation tier for context compression execution."""

    PRIMARY_LONG_WINDOW = "primary_long_window"        # Native long context LLM (>64k/128k)
    MAP_REDUCE_FALLBACK = "map_reduce_fallback"        # Chunked hierarchical map-reduce
    LOCAL_DETERMINISTIC_RESCUE = "local_deterministic_rescue"  # Lossless deterministic excerpting


@dataclass(frozen=True)
class ModelWindowSpec:
    """Hardware and context window specifications of a target compression model."""

    model_name: str
    context_window: int
    max_output_tokens: int = 4096
    safety_headroom_ratio: float = 1.25
    is_local: bool = False

    @property
    def safe_input_capacity(self) -> int:
        """Maximum safe input tokens allowed before triggering truncation."""
        usable = self.context_window - self.max_output_tokens
        return max(int(usable / self.safety_headroom_ratio), 1024)


@dataclass(frozen=True)
class CapacityAssertionResult:
    """Outcome of physical window capacity assertion."""

    passed: bool
    required_tokens: int
    model_window: int
    safe_input_capacity: int
    deficit_tokens: int
    error_message: str | None = None


@dataclass(frozen=True)
class ChunkedSummaryNode:
    """Individual chunk slice and summary payload in hierarchical map-reduce."""

    chunk_index: int
    total_chunks: int
    token_count: int
    extracted_summary: str
    key_entities: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CompressionTransparencyHudState:
    """Transparent HUD state broadcasted to clients to disclose compression mode."""

    is_degraded: bool
    tier: CompressionFallbackTier
    model_used: str
    badge_label: str
    badge_color: str     # green, yellow, orange
    user_alert_message: str
    fidelity_score: float
    fidelity_passed: bool


@dataclass(frozen=True)
class TurnBudgetWatchdogState:
    """Runtime state for the adaptive 500-turn task iteration watchdog."""

    current_turn: int
    allocated_budget: int
    max_ceiling: int = 500
    consecutive_idle_turns: int = 0
    total_progress_signals: int = 0
    can_continue: bool = True
    status_reason: str = "Active progress sustained"


@dataclass(frozen=True)
class AntiAmnesiaExecutionReport:
    """End-to-end audit report for guarded compression and watchdog monitoring."""

    fallback_tier: CompressionFallbackTier
    tokens_before: int
    tokens_after: int
    tokens_reclaimed: int
    compression_ratio: float
    hud_state: CompressionTransparencyHudState
    key_entities_preserved_ratio: float
    watchdog_state: TurnBudgetWatchdogState | None = None
