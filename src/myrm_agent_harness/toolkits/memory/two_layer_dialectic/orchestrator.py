"""
[INPUT]
models.py, base_context_engine.py, dialectic_engine.py

[OUTPUT]
TwoLayerDialecticOrchestrator, TwoLayerContextInjector, TwoLayerInvocationPayload, TwoLayerContextInjectionResult.
Orchestrates Layer 1 Base Context injection and Layer 2 Dialectic Reconciliation.

[POS]
Main coordinator facade for Item 112 in Harness framework.
Strict typing applied: No `Any` types allowed. Single file < 250 lines.
"""

import hashlib
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.two_layer_dialectic.base_context_engine import (
    BaseContextEngine,
)
from myrm_agent_harness.toolkits.memory.two_layer_dialectic.dialectic_engine import (
    DialecticReconciliationEngine,
)
from myrm_agent_harness.toolkits.memory.two_layer_dialectic.models import (
    BaseContextPayload,
    DialecticCadenceConfig,
    DialecticReconciliationResult,
    TwoLayerContextInjectionResult,
    TwoLayerInvocationPayload,
)


class TwoLayerDialecticOrchestrator:
    """Orchestrator coordinating Layer 1 base context and Layer 2 dialectic reconciliation."""

    def __init__(
        self,
        config: DialecticCadenceConfig | None = None,
        base_engine: BaseContextEngine | None = None,
        dialectic_engine: DialecticReconciliationEngine | None = None,
    ) -> None:
        self._config = config or DialecticCadenceConfig()
        self._base_engine = base_engine or BaseContextEngine(self._config)
        self._dialectic_engine = dialectic_engine or DialecticReconciliationEngine(self._config)
        self._cached_base_payloads: dict[str, BaseContextPayload] = {}

    @property
    def config(self) -> DialecticCadenceConfig:
        """Active cadence configuration."""
        return self._config

    @property
    def base_engine(self) -> BaseContextEngine:
        """Underlying BaseContextEngine."""
        return self._base_engine

    @property
    def dialectic_engine(self) -> DialecticReconciliationEngine:
        """Underlying DialecticReconciliationEngine."""
        return self._dialectic_engine

    def assemble_injection(
        self,
        session_id: str,
        turn: int,
        session_summary: str,
        peer_cards: list[str] | None = None,
        candidate_memories: list[str] | None = None,
        force_refresh_base: bool = False,
        force_dialectic: bool = False,
    ) -> TwoLayerContextInjectionResult:
        """Assemble dual-layer context blocks under cadence controls."""
        cards = peer_cards or []
        memories = candidate_memories or []

        # Layer 1 Base Context compilation/caching
        cached = self._cached_base_payloads.get(session_id)
        needs_refresh = (
            cached is None
            or force_refresh_base
            or turn == 0
            or (turn - cached.refreshed_at_turn >= self._config.context_cadence)
        )

        if needs_refresh or cached is None:
            cards_summary = ", ".join(cards)
            hash_src = f"{session_id}:{turn}:{session_summary}:{cards_summary}"
            cache_hash = hashlib.sha256(hash_src.encode()).hexdigest()[:16]
            payload = BaseContextPayload(
                session_id=session_id,
                session_summary=session_summary,
                standing_peer_cards=cards,
                cache_control_hash=cache_hash,
                refreshed_at_turn=turn,
                created_at=datetime.now(UTC).isoformat(),
                generation_turn=turn,
                estimated_tokens=max(20, len(session_summary + cards_summary) // 4),
            )
            self._cached_base_payloads[session_id] = payload
        else:
            payload = cached

        layer1_text = payload.formatted_user_tail_block()

        # Layer 2 Dialectic reconciliation check
        should_run_dialectic = force_dialectic or (turn % self._config.dialectic_cadence == 0)
        layer2_block = ""
        overhead = payload.estimated_tokens
        dialectic_res: DialecticReconciliationResult | None = None

        if should_run_dialectic and len(memories) >= 1:
            if len(memories) >= 2:
                reconcile_results = self._dialectic_engine.reconcile_all(
                    memories, depth=self._config.dialectic_depth
                )
                if reconcile_results:
                    dialectic_res = reconcile_results[0]
            if dialectic_res is None:
                conflicts = self._dialectic_engine.detect_conflicts(memories, "")
                dialectic_res = self._dialectic_engine.reconcile(
                    session_id=session_id,
                    turn_index=turn,
                    conflicts=conflicts,
                    depth=self._config.dialectic_depth,
                )

            if dialectic_res:
                statement = dialectic_res.resolved_statement or dialectic_res.reconciled_directive
                layer2_block = (
                    "<dialectic_reconciliation>\n"
                    f"  <resolution>{statement}</resolution>\n"
                    f"  <rationale>{dialectic_res.rationale}</rationale>\n"
                    "</dialectic_reconciliation>"
                )
                overhead += dialectic_res.token_cost_estimate

        return TwoLayerContextInjectionResult(
            layer1_base_context=layer1_text,
            layer2_dialectic_block=layer2_block,
            injected_position="user_message_tail",
            is_cache_safe=True,
            token_overhead=overhead,
            session_id=session_id,
            turn_index=turn,
            base_context=payload,
            dialectic_result=dialectic_res,
            total_token_overhead=overhead,
            kv_cache_preserved=True,
        )

    def get_cached_base_context(self, session_id: str) -> BaseContextPayload | None:
        """Retrieve cached Layer 1 base context payload if present."""
        return self._cached_base_payloads.get(session_id)

    def reset_session(self, session_id: str) -> None:
        """Evict cadence cache for session."""
        self._cached_base_payloads.pop(session_id, None)
        self._base_engine.invalidate(session_id)

    def prepare_turn(
        self,
        session_id: str,
        turn_index: int,
        raw_user_message: str,
        session_summary: str,
        peer_card_summary: str,
        historical_assertions: list[str] | None = None,
        force_dialectic: bool = False,
    ) -> TwoLayerInvocationPayload:
        """Prepares a turn payload by applying Layer 1 injection and conditional Layer 2 reconciliation."""
        assertions = historical_assertions or []
        res = self.assemble_injection(
            session_id=session_id,
            turn=turn_index,
            session_summary=session_summary,
            peer_cards=[peer_card_summary] if peer_card_summary else [],
            candidate_memories=assertions,
            force_dialectic=force_dialectic,
        )

        augmented_message = f"{raw_user_message.rstrip()}\n\n<!-- [BASE_CONTEXT_KV_CACHE_PROTECTED] -->\n{res.layer1_base_context}"
        if res.layer2_dialectic_block:
            augmented_message += f"\n\n<!-- [DIALECTIC_RECONCILIATION_DIRECTIVE] -->\n{res.layer2_dialectic_block}"

        res.augmented_user_message = augmented_message
        return res


TwoLayerContextInjector = TwoLayerDialecticOrchestrator
