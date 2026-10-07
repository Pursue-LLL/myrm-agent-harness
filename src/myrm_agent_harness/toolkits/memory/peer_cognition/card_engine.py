# [POS]: myrm_agent_harness.toolkits.memory.peer_cognition.card_engine
# [INPUT]: models.py, graph_engine.py
# [OUTPUT]: PeerPersonaCardEngine

"""Self-evolving standing persona card engine and low-token context projector.

P0 delivery for Item 110 in topic_01 memory roadmap.
Curates, evolves, and projects compact social cognition cards (<150 words)
for each active peer to eliminate role ambiguity and unowned memory drift.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.peer_cognition.graph_engine import (
    PeerCognitionGraphStore,
)
from myrm_agent_harness.toolkits.memory.peer_cognition.models import (
    PeerCognitionProjection,
    PeerIdentity,
    PeerPersonaCard,
    PeerType,
)

logger = logging.getLogger(__name__)


class PeerPersonaCardEngine:
    """Engine managing persona cards, incremental evolution, and prompt projections."""

    def __init__(self, graph_store: PeerCognitionGraphStore | None = None) -> None:
        self._graph_store = graph_store or PeerCognitionGraphStore()
        self._cards: dict[str, PeerPersonaCard] = {}

    @property
    def graph_store(self) -> PeerCognitionGraphStore:
        """Underlying graph store."""
        return self._graph_store

    def create_or_update_card(
        self,
        peer_id: str,
        core_responsibilities: list[str] | None = None,
        decision_style: str | None = None,
        standing_preferences: dict[str, str] | None = None,
        summary_digest: str | None = None,
    ) -> PeerPersonaCard:
        """Create or mutate a standing persona card for a peer."""
        peer = self._graph_store.get_peer(peer_id)
        if peer is None:
            # Auto-register fallback peer identity if not registered
            peer = PeerIdentity(
                peer_id=peer_id,
                peer_type=PeerType.USER_PEER,
                display_name=peer_id,
            )
            self._graph_store.register_peer(peer)

        card = self._cards.get(peer_id)
        if card is None:
            card = PeerPersonaCard(
                peer_id=peer_id,
                peer_type=peer.peer_type,
                display_name=peer.display_name,
                core_responsibilities=list(core_responsibilities or []),
                decision_style=decision_style or "balanced",
                standing_preferences=dict(standing_preferences or {}),
                summary_digest=summary_digest or "",
            )
        else:
            if core_responsibilities is not None:
                card.core_responsibilities = list(core_responsibilities)
            if decision_style is not None:
                card.decision_style = decision_style
            if standing_preferences is not None:
                card.standing_preferences.update(standing_preferences)
            if summary_digest is not None:
                card.summary_digest = summary_digest

        if not card.summary_digest:
            card.summary_digest = self._synthesize_digest(card)

        card.updated_at = datetime.now(UTC).isoformat()
        self._cards[peer_id] = card
        return card

    def get_card(self, peer_id: str) -> PeerPersonaCard | None:
        """Retrieve persona card for a peer."""
        return self._cards.get(peer_id)

    def list_cards(self, peer_type: PeerType | None = None) -> list[PeerPersonaCard]:
        """List persona cards, optionally filtered by peer category."""
        if peer_type is None:
            return list(self._cards.values())
        return [c for c in self._cards.values() if c.peer_type == peer_type]

    def record_interaction(
        self,
        peer_id: str,
        success: bool,
        preference_deltas: dict[str, str] | None = None,
    ) -> PeerPersonaCard:
        """Incrementally evolve persona card following an interaction outcome."""
        card = self.create_or_update_card(peer_id)
        card.interaction_count += 1

        # Smooth updating of success rate and trust score
        alpha = 0.2  # Exponential moving weight
        outcome_val = 1.0 if success else 0.0
        card.success_rate = (1.0 - alpha) * card.success_rate + alpha * outcome_val
        card.trust_score = max(0.0, min(1.0, card.success_rate * 0.9 + 0.1))

        if preference_deltas:
            card.standing_preferences.update(preference_deltas)

        # Refresh digest upon evolution
        card.summary_digest = self._synthesize_digest(card)
        card.updated_at = datetime.now(UTC).isoformat()
        self._graph_store.touch_peer(peer_id)
        return card

    def generate_projection(self, peer_ids: list[str]) -> PeerCognitionProjection:
        """Generate low-token formatted context block ready for prompt injection."""
        lines: list[str] = ["[PEER SOCIAL COGNITION CONTEXT]"]
        included: list[str] = []

        for pid in peer_ids:
            card = self._cards.get(pid)
            if not card:
                peer = self._graph_store.get_peer(pid)
                if peer:
                    card = self.create_or_update_card(pid)
            if card:
                lines.append(f"- @{card.peer_type.value} {card.display_name} (id: {card.peer_id}):")
                if card.core_responsibilities:
                    lines.append(f"  * Responsibilities: {', '.join(card.core_responsibilities)}")
                if card.standing_preferences:
                    pref_str = ", ".join(f"{k}={v}" for k, v in list(card.standing_preferences.items())[:5])
                    lines.append(f"  * Preferences: {pref_str}")
                lines.append(f"  * Style: {card.decision_style} | Trust: {card.trust_score:.2f}")
                if card.summary_digest:
                    lines.append(f"  * Summary: {card.summary_digest}")
                included.append(pid)

        if len(lines) == 1:
            return PeerCognitionProjection(
                formatted_prompt_block="",
                token_cost_estimate=0,
                targeted_peers=[],
            )

        block = "\n".join(lines)
        token_estimate = max(1, len(block) // 4)
        return PeerCognitionProjection(
            formatted_prompt_block=block,
            token_cost_estimate=token_estimate,
            targeted_peers=included,
        )

    def align_collaborator_roles(self, peer_ids: list[str]) -> dict[str, list[str]]:
        """Map collaborator peers to their respective explicit responsibilities."""
        role_map: dict[str, list[str]] = {}
        for pid in peer_ids:
            card = self._cards.get(pid)
            if card:
                role_map[pid] = list(card.core_responsibilities)
            else:
                role_map[pid] = []
        return role_map

    def _synthesize_digest(self, card: PeerPersonaCard) -> str:
        """Synthesize concise (<150 words) natural language digest."""
        duties = ", ".join(card.core_responsibilities) if card.core_responsibilities else "general collaboration"
        prefs = (
            "; ".join(f"{k}: {v}" for k, v in list(card.standing_preferences.items())[:3])
            if card.standing_preferences
            else "none recorded"
        )
        return (
            f"Role: {card.display_name} ({card.peer_type.value}). "
            f"Focused on {duties}. "
            f"Decision style: {card.decision_style} with trust {card.trust_score:.2f}. "
            f"Key preferences: {prefs}."
        )
