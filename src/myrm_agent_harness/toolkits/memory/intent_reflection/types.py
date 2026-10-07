"""Typed data contracts for the intent reflection subsystem.

[INPUT]
- toolkits.memory.types::ProceduralMemory (POS: Memory type system foundation.)

[OUTPUT]
- IntentTier: Tiered operational intent classification levels.
- IntentClassificationResult: Telemetry outcome of an intent classification evaluation.
- PlaybookActivationDecision: Outcome of playbook rule activation and retrieval filtering.
- ReflectionProbeProtocol: Protocol for optional sidecar neural reflection probes (e.g. 0.6B local model).

[POS]
Typed data contracts for the intent reflection subsystem.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.types import ProceduralMemory


class IntentTier(StrEnum):
    """Tiered operational intent classification levels."""

    TIER_0_FAST_PATH = "tier_0_fast_path"
    TIER_1_CODE_EXECUTION = "tier_1_code_execution"
    TIER_2_KNOWLEDGE_CONTENT = "tier_2_knowledge_content"
    TIER_3_DEEP_REASONING = "tier_3_deep_reasoning"


@dataclass(frozen=True)
class IntentClassificationResult:
    """Telemetry outcome of an intent classification evaluation."""

    tier: IntentTier
    confidence: float
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    suggested_facets: tuple[str, ...] = field(default_factory=tuple)
    source: str = "heuristic"
    reason: str = ""


@dataclass(frozen=True)
class PlaybookActivationDecision:
    """Outcome of playbook rule activation and retrieval filtering."""

    tier: IntentTier
    bypass_retrieval: bool
    active_facets: tuple[str, ...]
    activated_rules: tuple["ProceduralMemory", ...]
    suppressed_rules_count: int
    decision_reason: str


@runtime_checkable
class ReflectionProbeProtocol(Protocol):
    """Protocol for optional sidecar neural reflection probes (e.g. 0.6B local model)."""

    def classify(
        self,
        query: str,
        context: dict[str, str] | None = None,
    ) -> IntentClassificationResult | None:
        """Classify query into an intent result, or return None if undetermined."""
        ...
