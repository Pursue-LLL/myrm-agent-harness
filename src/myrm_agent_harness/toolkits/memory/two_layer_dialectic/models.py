"""
[INPUT]
None (Fundamental domain models for Item 112).

[OUTPUT]
DialecticReasoningLevel, DialecticPassKind, DialecticCadenceConfig, DialecticReconciliationConfig,
BaseContextBundle, BaseContextPayload, ConflictItem, DialecticConflictCandidate,
DialecticPassRecord, DialecticReconciliationResult, TwoLayerInvocationPayload, TwoLayerContextInjectionResult.

[POS]
Data structures for Two-Layer Context Injection & Multi-Pass Dialectic Reconciliation Suite.
Strict typing applied: No `Any` types allowed. Single file < 250 lines.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class DialecticReasoningLevel(StrEnum):
    """Reasoning compute allocation for dialectic synthesis passes."""

    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


class DialecticPassKind(StrEnum):
    """Reasoning pass stages in dialectic loop."""

    INSPECTION = "inspection"
    SYNTHESIS = "synthesis"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True)
class DialecticCadenceConfig:
    """Three orthogonal control knobs balancing latency, cost, and reconciliation depth.

    Attributes:
        context_cadence: Refresh interval in turns for Layer 1 Base Context.
        dialectic_cadence: Turn interval for automated dialectic conflict checks.
        dialectic_depth: Number of passes in dialectic reconciliation (1-3).
        dialectic_reasoning_level: Model reasoning tier to allocate.
        conflict_similarity_cutoff: Similarity and conflict threshold.
    """

    context_cadence: int = 5
    dialectic_cadence: int = 3
    dialectic_depth: int = 2
    dialectic_reasoning_level: DialecticReasoningLevel = DialecticReasoningLevel.STANDARD
    conflict_similarity_cutoff: float = 0.65


DialecticReconciliationConfig = DialecticCadenceConfig


@dataclass
class BaseContextBundle:
    """Layer 1: Low-frequency immutable base context snapshot.

    Injected dynamically at the tail of user message to protect system prompt KV Cache.
    """

    session_id: str = ""
    session_summary: str = ""
    peer_card_summary: str = ""
    standing_peer_cards: list[str] = field(default_factory=list)
    cache_control_hash: str = ""
    refreshed_at_turn: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    generation_turn: int = 0
    cadence_interval: int = 5
    estimated_tokens: int = 0
    system_prompt_frozen: bool = True
    tail_injection_xml: str = ""

    def formatted_user_tail_block(self) -> str:
        """Format base context block to append to user message."""
        hash_val = self.cache_control_hash or hashlib.sha256(self.session_summary.encode()).hexdigest()[:16]
        peers_str = ", ".join(self.standing_peer_cards) if self.standing_peer_cards else self.peer_card_summary
        return (
            "\n\n<!-- [BASE_CONTEXT_KV_CACHE_PROTECTED] -->\n"
            f"<base_context cache_hash=\"{hash_val}\" session=\"{self.session_id}\" turn=\"{self.refreshed_at_turn or self.generation_turn}\">\n"
            f"  <session_summary>{self.session_summary}</session_summary>\n"
            f"  <peer_cards>{peers_str}</peer_cards>\n"
            "</base_context>"
        )


BaseContextPayload = BaseContextBundle


@dataclass
class ConflictItem:
    """Specific dialectic contradiction identified between memory and current goal."""

    conflict_id: str = ""
    source_topic: str = ""
    prior_stance: str = ""
    current_stance: str = ""
    severity_score: float = 1.0
    statement_a: str = ""
    statement_b: str = ""
    subject_domain: str = ""
    conflict_score: float = 1.0


DialecticConflictCandidate = ConflictItem


@dataclass
class DialecticPassRecord:
    """Audit record for a single dialectic pass."""

    pass_number: int  # 0: Inspection/Detection, 1: Synthesis, 2: Reconciliation
    pass_name: str
    thought_summary: str
    output_statement: str


@dataclass
class DialecticReconciliationResult:
    """Layer 2: Multi-pass dialectic reconciliation directive."""

    session_id: str = ""
    turn_index: int = 0
    conflicts_detected: list[ConflictItem] = field(default_factory=list)
    passes: list[DialecticPassRecord] = field(default_factory=list)
    reconciled_directive: str = ""
    dialectic_depth_executed: int = 0
    token_cost_estimate: int = 0
    kv_cache_preserved: bool = True
    passes_executed: list[DialecticPassKind | str] = field(default_factory=list)
    resolved_statement: str = ""
    superseded_statements: list[str] = field(default_factory=list)
    confidence: float = 1.0
    rationale: str = ""

    def formatted_directive_block(self) -> str:
        """Format dialectic reconciliation block for execution context."""
        directive = self.reconciled_directive or self.resolved_statement
        if not directive:
            return ""
        return (
            f"<dialectic_reconciliation turn=\"{self.turn_index}\" depth=\"{self.dialectic_depth_executed or len(self.passes_executed)}\">\n"
            f"  <resolution>{directive}</resolution>\n"
            f"  <rationale>{self.rationale}</rationale>\n"
            "</dialectic_reconciliation>"
        )


@dataclass
class TwoLayerInvocationPayload:
    """End-to-end prepared invocation payload for Agent runtime."""

    session_id: str = ""
    turn_index: int = 0
    augmented_user_message: str = ""
    base_context: BaseContextBundle | None = None
    dialectic_result: DialecticReconciliationResult | None = None
    total_token_overhead: int = 0
    kv_cache_preserved: bool = True
    layer1_base_context: str = ""
    layer2_dialectic_block: str = ""
    injected_position: str = "user_message_tail"
    is_cache_safe: bool = True
    token_overhead: int = 0


TwoLayerContextInjectionResult = TwoLayerInvocationPayload
