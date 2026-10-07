"""Strongly typed contracts for Token Burn Rate Governor and Consumption Shield (Item 220).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- BurnRateZone: Operational severity zones for token consumption rates.
- ToolLeanMode: Policy for dynamically pruning tool schemas to cut prompt noise.
- TokenUsageRecord: Atomic ledger entry capturing tokens consumed by an inference call.
- BurnRateTelemetry: Computed rolling metrics assessing tokens per minute/hour.
- LeanToolPruningDecision: Outcome of tool schema slimming based on intent and burn rate.
- RateLimitBackoffDecision: Adaptive backoff and candidate model fallback outcome for 429 errors.
- TokenGovernorConfig: Tunable threshold parameters and safety policies.

[POS]
- Safeguards long-running agent workflows from runaway token exhaustion and frequent 429
- provider rate-limits by combining rolling burn rate tracking, lean tools, and smart backoff.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class BurnRateZone(str, enum.Enum):
    """Operational health zones reflecting token burn velocity."""

    NORMAL_GREEN = "normal_green"
    SPIKE_YELLOW = "spike_yellow"
    THROTTLE_ORANGE = "throttle_orange"
    EXHAUSTION_RED = "exhaustion_red"


class ToolLeanMode(str, enum.Enum):
    """Dynamic pruning modes for reducing prompt floor noise from tool schemas."""

    FULL_SURFACE = "full_surface"
    LEAN_PRUNED = "lean_pruned"
    MINIMAL_CONVERSATIONAL = "minimal_conversational"


@dataclass(frozen=True, slots=True)
class TokenUsageRecord:
    """Atomic token consumption record for a single LLM or tool interaction."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_name: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes record to dictionary."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "model_name": self.model_name,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class BurnRateTelemetry:
    """Rolling window metrics evaluating current token burn rate and governor zone."""

    session_id: str
    window_seconds: int
    total_tokens_in_window: int
    burn_rate_per_minute: float
    burn_rate_per_hour: float
    zone: BurnRateZone
    recommended_action: str
    sample_count: int

    def to_dict(self) -> dict[str, object]:
        """Serializes burn rate telemetry to dictionary."""
        return {
            "session_id": self.session_id,
            "window_seconds": self.window_seconds,
            "total_tokens_in_window": self.total_tokens_in_window,
            "burn_rate_per_minute": self.burn_rate_per_minute,
            "burn_rate_per_hour": self.burn_rate_per_hour,
            "zone": self.zone.value,
            "recommended_action": self.recommended_action,
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True, slots=True)
class LeanToolPruningDecision:
    """Structured decision detailing tool schema pruning to diminish floor noise."""

    mode: ToolLeanMode
    active_tool_names: list[str]
    pruned_tool_names: list[str]
    noise_reduction_ratio: float
    reason: str

    def to_dict(self) -> dict[str, object]:
        """Serializes lean tool pruning decision."""
        return {
            "mode": self.mode.value,
            "active_tool_names": list(self.active_tool_names),
            "pruned_tool_names": list(self.pruned_tool_names),
            "noise_reduction_ratio": self.noise_reduction_ratio,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RateLimitBackoffDecision:
    """Adaptive backoff and model downgrade decision when encountering provider 429 responses."""

    should_retry: bool
    backoff_seconds: float
    suggest_model_fallback: bool
    fallback_model_candidate: str | None
    attempt_index: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        """Serializes rate-limit backoff decision."""
        return {
            "should_retry": self.should_retry,
            "backoff_seconds": self.backoff_seconds,
            "suggest_model_fallback": self.suggest_model_fallback,
            "fallback_model_candidate": self.fallback_model_candidate,
            "attempt_index": self.attempt_index,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class TokenGovernorConfig:
    """Tunable configuration thresholds for burn rate monitoring and runaway shielding."""

    rolling_window_seconds: int = 60
    yellow_spike_tpm: int = 40000
    orange_throttle_tpm: int = 80000
    red_exhaustion_tpm: int = 150000
    max_history_records: int = 500
    default_backoff_base_seconds: float = 2.0
    max_backoff_seconds: float = 60.0
    max_retry_attempts: int = 4
