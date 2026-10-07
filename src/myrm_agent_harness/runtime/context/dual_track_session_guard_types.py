"""Type definitions for Dual-Track Session Scenario Context Isolator and Token Burn Guard.

Defines schemas for track segregation (Dev vs Thinking/Q&A), intent classifications,
unintentional context burn guard decisions, and advisory telemetry.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SessionScenarioTrack: Execution track specifying depth of workspace and tooling attachment.
- IntentCategory: Categorization of user input intent.
- BurnGuardAction: Enforcement action determined by TokenBurnGuard.
- BurnGuardDecision: Decision outcome containing throttling actions and cost-saving metrics.
- DualTrackContextAssembly: Composite context output tailored for the active track and guard policy.

[POS]
Type definitions for Dual-Track Session Scenario Context Isolator and Token Burn Guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SessionScenarioTrack(StrEnum):
    """Execution track specifying depth of workspace and tooling attachment."""

    DEV_TRACK = "dev_track"
    THINKING_QA_TRACK = "thinking_qa_track"


class IntentCategory(StrEnum):
    """Categorization of user input intent."""

    ENGINEERING_DEV = "engineering_dev"
    GENERAL_QA_OR_CHAT = "general_qa_or_chat"
    AMBIGUOUS = "ambiguous"


class BurnGuardAction(StrEnum):
    """Enforcement action determined by TokenBurnGuard."""

    PASSTHROUGH = "passthrough"
    THROTTLE_WORKSPACE_CONTEXT = "throttle_workspace_context"
    BLOCK_AND_SUGGEST = "block_and_suggest"


@dataclass(frozen=True)
class BurnGuardDecision:
    """Decision outcome containing throttling actions and cost-saving metrics."""

    action: BurnGuardAction
    detected_intent: IntentCategory
    workspace_stripped: bool
    estimated_tokens_saved: int
    savings_percentage: float
    user_advisory_message: str | None


@dataclass(frozen=True)
class DualTrackContextAssembly:
    """Composite context output tailored for the active track and guard policy."""

    active_track: SessionScenarioTrack
    workspace_included: bool
    assembled_system_prompt: str
    decision: BurnGuardDecision
