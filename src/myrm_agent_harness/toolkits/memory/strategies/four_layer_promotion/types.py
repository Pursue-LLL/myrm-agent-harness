"""Four-layer memory hierarchy and tri-channel promotion data contracts.

[INPUT]
- None (Self-contained foundational dataclasses and StrEnums)

[OUTPUT]
- MemoryLayer: WORKING, RAW_EPISODIC, CONSOLIDATED_EPISODIC, SEMANTIC_POLICY, CAPABILITY_METHOD
- PromotionChannel: REPEATED_ACROSS_SESSIONS, TOOL_FAILURE_EVIDENCE, EXPLICIT_USER_INSTRUCTION
- ExposureSource: INTERNAL_CHAT, EXTERNAL_UNTRUSTED
- CandidateStatement, CapabilityMethod, PromotionDecision, RulesComplianceItem

[POS]
Foundational contracts for Hermes-grade four-layer memory governance,
two-step Map-Reduce consolidation, and tri-channel code-level promotion gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoryLayer(StrEnum):
    """Four-layer memory hierarchy defining progressive lifecycle maturity."""

    WORKING = "working"
    RAW_EPISODIC = "raw_episodic"
    CONSOLIDATED_EPISODIC = "consolidated_episodic"
    SEMANTIC_POLICY = "semantic_policy"
    CAPABILITY_METHOD = "capability_method"


class PromotionChannel(StrEnum):
    """Tri-channel code-level verification paths for long-term promotion."""

    REPEATED_ACROSS_SESSIONS = "repeated_across_sessions"
    TOOL_FAILURE_EVIDENCE = "tool_failure_evidence"
    EXPLICIT_USER_INSTRUCTION = "explicit_user_instruction"


class ExposureSource(StrEnum):
    """Source provenance tracking to prevent Exposure -> Memory -> Behavior poisoning."""

    INTERNAL_CHAT = "internal_chat"
    EXTERNAL_UNTRUSTED = "external_untrusted"


@dataclass(frozen=True, slots=True)
class CandidateStatement:
    """A self-contained candidate statement extracted during the Map phase."""

    statement: str
    supported_event_ids: tuple[str, ...]
    session_id: str
    exposure_source: ExposureSource = ExposureSource.INTERNAL_CHAT
    has_tool_failure: bool = False
    is_explicit_user_instruction: bool = False


@dataclass(frozen=True, slots=True)
class CapabilityMethod:
    """Actionable capability method card distilled from repeated success/failure."""

    method_id: str
    title: str
    applies_when: str
    method_steps: tuple[str, ...]
    validation_criteria: str
    failure_signals: tuple[str, ...]
    supported_event_ids: tuple[str, ...]
    promotion_channel: PromotionChannel


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Code-level deterministic promotion decision produced by TriChannelPromotionGate."""

    promoted: bool
    channel: PromotionChannel | None
    reason: str
    method_card: CapabilityMethod | None = None


@dataclass(frozen=True, slots=True)
class RulesComplianceItem:
    """Structured rule compliance evaluation item for contract verification."""

    rule_id: str
    statement: str
    compliant: bool
    rationale: str
