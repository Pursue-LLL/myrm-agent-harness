# [POS]: myrm_agent_harness.toolkits.memory.two_layer_dialectic.injector
# [INPUT]: BaseContextPayload, DialecticReconciliationConfig, TwoLayerContextInjectionResult, MultiPassDialecticReconciler
# [OUTPUT]: TwoLayerContextInjector

"""Dual-layer context injection engine preserving LLM Prompt Cache while resolving contradictions.

Layer 1 (Base Context): Low-cadence, deterministic prefix hash to maximize KV Cache hits.
Layer 2 (Dialectic Reconciliation): High-accuracy conflict resolution injected at user message tail.
"""

from __future__ import annotations

import hashlib
from typing import Final

from myrm_agent_harness.toolkits.memory.two_layer_dialectic.models import (
    BaseContextPayload,
    DialecticReconciliationConfig,
    DialecticReconciliationResult,
    TwoLayerContextInjectionResult,
)
from myrm_agent_harness.toolkits.memory.two_layer_dialectic.reconciler import MultiPassDialecticReconciler

_DEFAULT_POSITION: Final[str] = "user_message_tail"


def _compute_cache_hash(session_summary: str, peer_cards: list[str]) -> str:
    """Compute deterministic SHA-256 fingerprint for base context components."""
    content = f"summary:{session_summary.strip()}|peers:{'|'.join(sorted(p.strip() for p in peer_cards))}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _format_base_context_xml(payload: BaseContextPayload) -> str:
    """Render Layer 1 base context with explicit cache hash boundaries."""
    peers_xml = "\n".join(f"  <peer_card>{card.strip()}</peer_card>" for card in payload.standing_peer_cards)
    return (
        f'<base_context cache_hash="{payload.cache_control_hash}" turn="{payload.refreshed_at_turn}">\n'
        f"  <session_summary>{payload.session_summary.strip()}</session_summary>\n"
        f"  <standing_peers>\n{peers_xml}\n  </standing_peers>\n"
        f"</base_context>"
    )


def _format_dialectic_xml(results: list[DialecticReconciliationResult]) -> str:
    """Render Layer 2 dialectic resolutions for tail injection."""
    if not results:
        return ""
    resolutions_xml = "\n".join(
        f'  <resolution confidence="{r.confidence:.2f}">\n'
        f"    <resolved>{r.resolved_statement.strip()}</resolved>\n"
        f"    <superseded>{', '.join(r.superseded_statements)}</superseded>\n"
        f"    <rationale>{r.rationale.strip()}</rationale>\n"
        f"  </resolution>"
        for r in results
    )
    return f"<dialectic_reconciliation>\n{resolutions_xml}\n</dialectic_reconciliation>"


class TwoLayerContextInjector:
    """Orchestrates cadence-governed dual-layer injection to optimize caching and eliminate memory conflicts."""

    def __init__(
        self,
        config: DialecticReconciliationConfig | None = None,
        reconciler: MultiPassDialecticReconciler | None = None,
    ) -> None:
        self._config = config or DialecticReconciliationConfig()
        self._reconciler = reconciler or MultiPassDialecticReconciler(self._config)
        self._last_base_turn: dict[str, int] = {}
        self._last_dialectic_turn: dict[str, int] = {}
        self._cached_base_contexts: dict[str, BaseContextPayload] = {}

    @property
    def config(self) -> DialecticReconciliationConfig:
        return self._config

    @property
    def reconciler(self) -> MultiPassDialecticReconciler:
        return self._reconciler

    def get_cached_base_context(self, session_id: str) -> BaseContextPayload | None:
        """Retrieve current cached Layer 1 payload for a session."""
        return self._cached_base_contexts.get(session_id)

    def reset_session(self, session_id: str) -> None:
        """Evict cached cadence states and base context for a given session."""
        self._last_base_turn.pop(session_id, None)
        self._last_dialectic_turn.pop(session_id, None)
        self._cached_base_contexts.pop(session_id, None)

    def build_base_context(
        self,
        session_id: str,
        turn: int,
        session_summary: str,
        peer_cards: list[str] | None = None,
        force_refresh: bool = False,
    ) -> tuple[BaseContextPayload, bool]:
        """Compile Layer 1 Base Context according to context cadence.

        Returns tuple of (payload, was_refreshed).
        """
        active_peers = peer_cards or []
        cached = self._cached_base_contexts.get(session_id)
        last_turn = self._last_base_turn.get(session_id, -1)

        needs_refresh = (
            force_refresh
            or cached is None
            or (turn - last_turn) >= self._config.context_cadence
        )

        if not needs_refresh and cached is not None:
            return cached, False

        cache_hash = _compute_cache_hash(session_summary, active_peers)
        new_payload = BaseContextPayload(
            session_summary=session_summary,
            standing_peer_cards=active_peers,
            cache_control_hash=cache_hash,
            refreshed_at_turn=turn,
        )
        self._cached_base_contexts[session_id] = new_payload
        self._last_base_turn[session_id] = turn
        return new_payload, True

    def run_dialectic_reconciliation(
        self,
        session_id: str,
        turn: int,
        candidate_memories: list[str] | None = None,
        force: bool = False,
    ) -> list[DialecticReconciliationResult]:
        """Perform on-demand Layer 2 dialectic contradiction arbitration according to cadence."""
        if not candidate_memories or len(candidate_memories) < 2:
            return []

        last_dialectic = self._last_dialectic_turn.get(session_id)
        needs_dialectic = (
            force
            or last_dialectic is None
            or (turn - last_dialectic) >= self._config.dialectic_cadence
        )

        if not needs_dialectic:
            return []

        resolutions = self._reconciler.reconcile_all(candidate_memories)
        self._last_dialectic_turn[session_id] = turn
        return resolutions

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
        """Compose dual-layer context blocks, maintaining strict prefix cache immutability."""
        base_payload, _ = self.build_base_context(
            session_id=session_id,
            turn=turn,
            session_summary=session_summary,
            peer_cards=peer_cards,
            force_refresh=force_refresh_base,
        )
        base_text = _format_base_context_xml(base_payload)

        resolutions = self.run_dialectic_reconciliation(
            session_id=session_id,
            turn=turn,
            candidate_memories=candidate_memories,
            force=force_dialectic,
        )
        dialectic_text = _format_dialectic_xml(resolutions)

        # Rough token estimation (~4 chars per token)
        total_len = len(base_text) + len(dialectic_text)
        token_est = max(1, total_len // 4)

        return TwoLayerContextInjectionResult(
            layer1_base_context=base_text,
            layer2_dialectic_block=dialectic_text,
            injected_position=_DEFAULT_POSITION,
            is_cache_safe=True,
            token_overhead=token_est,
        )
