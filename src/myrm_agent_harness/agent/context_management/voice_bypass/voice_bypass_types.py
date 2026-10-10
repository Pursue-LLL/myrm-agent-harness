"""Type definitions for voice command local bypass and tiered intent routing.

[INPUT]
None. Standalone type definitions for voice command dispatch.

[OUTPUT]
VoiceIntentTier, VoiceActionCategory, VoiceBypassAction, VoiceCommandMatchResult,
VoiceBypassConfig.

[POS]
Type definitions in context_management/voice_bypass/voice_bypass_types.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class VoiceIntentTier(StrEnum):
    """Routing tier for voice utterances."""

    TIER0_LOCAL_BYPASS = "tier0_local_bypass"
    TIER1_AGENT_LLM = "tier1_agent_llm"


class VoiceActionCategory(StrEnum):
    """Categorization of local zero-token actions."""

    EXECUTION_CONTROL = "execution_control"
    SESSION_NAVIGATE = "session_navigate"
    VIEW_SCROLL = "view_scroll"
    AGENT_SWITCH = "agent_switch"
    SYSTEM_EXPORT = "system_export"


@dataclass(frozen=True, slots=True)
class VoiceBypassAction:
    """Action payload emitted by local Tier-0 resolution."""

    action_id: str
    category: VoiceActionCategory
    target_payload: str = ""
    parameters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VoiceCommandMatchResult:
    """Result of tiered voice command routing evaluation."""

    tier: VoiceIntentTier
    raw_utterance: str
    normalized_command: str
    is_bypass: bool
    action: VoiceBypassAction | None = None
    confidence: float = 1.0
    tokens_saved: int = 0
    estimated_latency_ms: float = 5.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class VoiceBypassConfig:
    """Configuration for local deterministic voice command bypass."""

    enabled: bool = True
    min_confidence_threshold: float = 0.85
    default_tokens_saved_estimate: int = 450
    allow_custom_patterns: bool = True
