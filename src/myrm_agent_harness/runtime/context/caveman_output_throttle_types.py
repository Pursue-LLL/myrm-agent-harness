"""Data contracts for Caveman Ultra-Compact Output Mode and Output Token Throttle."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CavemanThrottleMode(StrEnum):
    """Operational mode for ultra-compact token throttling."""

    OFF = "off"
    AGGRESSIVE = "aggressive"
    AUTO_ADAPTIVE = "auto_adaptive"
    EXECUTION_ONLY = "execution_only"


class ConversationIntentKind(StrEnum):
    """Intent classification of current execution cycle."""

    EXECUTION_AUTOMATION = "execution_automation"
    TOOL_PIPELINE = "tool_pipeline"
    EXPLANATORY_QA = "explanatory_qa"
    CREATIVE_WRITING = "creative_writing"


@dataclass(frozen=True)
class ThrottleDecision:
    """Policy decision determining whether to inject compact prompt and strip pleasantries."""

    mode_applied: CavemanThrottleMode
    should_inject_preamble: bool
    should_strip_pleasantries: bool
    reason: str


@dataclass(frozen=True)
class SanitizedOutputResult:
    """Result of post-generation verbosity stripping and token savings accounting."""

    original_text: str
    sanitized_text: str
    tokens_saved_estimate: int
    stripped_prefix: str | None
    stripped_suffix: str | None
