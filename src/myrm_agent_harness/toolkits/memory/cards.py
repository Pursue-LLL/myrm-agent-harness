"""A-MEM Zettelkasten Knowledge Card Network.

[INPUT]
- myrm_agent_harness.toolkits.memory.types::EvidenceReference (POS: Memory type system foundation for factual claims and citations)

[OUTPUT]
- AMemCard: Atomic Zettelkasten memory unit with decoupled evidence references and version lineage
- AMemZettelkastenNetwork: Bidirectional knowledge graph, lineage traversal, and digest exporter

[POS]
A-MEM Zettelkasten knowledge card network. Decouples verifiable evidence from derived conclusions, managing bidirectional associative graphs, evolutionary version lineages, and contextual subgraph exports.
"""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.types import EvidenceReference

__all__ = [
    "AMemCard",
    "AMemZettelkastenNetwork",
]


@dataclass(slots=True)
class AMemCard:
    """Atomic memory card following the Zettelkasten knowledge model.

    Decouples refined conclusions from historical raw evidence anchors, enabling
    auditable belief tracking and non-destructive cognitive evolution.
    """

    id: str
    title: str
    conclusion: str
    evidences: list[EvidenceReference] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    links: set[str] = field(default_factory=set)
    supersedes: str | None = None
    superseded_by: str | None = None
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Card is active if it has not been superseded by a newer belief version."""
        return self.superseded_by is None

    def render_markdown(self) -> str:
        """Render the card as human-and-agent readable Markdown."""
        status_tag = "[Active]" if self.is_active else f"[Superseded by {self.superseded_by}]"
        lines = [
            f"### Card [{self.id}]: {self.title} (v{self.version}) {status_tag}",
            f"**Conclusion**: {self.conclusion}",
        ]

        if self.tags:
            lines.append(f"**Tags**: {', '.join(sorted(self.tags))}")

        if self.links:
            lines.append(f"**Links**: {', '.join(sorted(self.links))}")

        if self.supersedes:
            lines.append(f"**Supersedes**: {self.supersedes}")

        if self.evidences:
            lines.append("**Evidence Anchors**:")
            for ev in self.evidences:
                snippet = f' "{ev.quote_snippet}"' if ev.quote_snippet else ""
                lines.append(f"  - Source: {ev.source_id}{snippet}")

        return "\n".join(lines)


class AMemZettelkastenNetwork:
    """Bidirectional knowledge topology and lineage manager for AMemCard instances.

    Maintains active indexes, bidirectional linkage, belief evolution chains,
    and contextual subgraph traversal for prompt injection.
    """

    def __init__(self) -> None:
        self._cards: dict[str, AMemCard] = {}
        self._incoming_links: dict[str, set[str]] = {}
        self._tag_index: dict[str, set[str]] = {}

    def __len__(self) -> int:
        return len(self._cards)

    def add_card(self, card: AMemCard) -> str:
        """Register a new memory card into the Zettelkasten network."""
        self._cards[card.id] = card

        # Index tags
        for tag in card.tags:
            self._tag_index.setdefault(tag, set()).add(card.id)

        # Index outgoing links
        for target_id in card.links:
            self._incoming_links.setdefault(target_id, set()).add(card.id)

        # Ensure card has entry in incoming index
        self._incoming_links.setdefault(card.id, set())
        return card.id

    def get_card(self, card_id: str) -> AMemCard | None:
        """Retrieve a card by its identifier."""
        return self._cards.get(card_id)

    def link(self, source_id: str, target_id: str) -> bool:
        """Create a directed link between two cards, updating reverse indexes."""
        source = self._cards.get(source_id)
        target = self._cards.get(target_id)
        if not source or not target:
            return False

        source.links.add(target_id)
        source.updated_at = datetime.now(UTC)
        self._incoming_links.setdefault(target_id, set()).add(source_id)
        return True

    def unlink(self, source_id: str, target_id: str) -> bool:
        """Remove a directed link between two cards."""
        source = self._cards.get(source_id)
        if not source or target_id not in source.links:
            return False

        source.links.remove(target_id)
        source.updated_at = datetime.now(UTC)
        if target_id in self._incoming_links:
            self._incoming_links[target_id].discard(source_id)
        return True

    def evolve(
        self,
        old_card_id: str,
        new_conclusion: str,
        *,
        new_evidences: Sequence[EvidenceReference] | None = None,
        title: str | None = None,
        reason: str = "",
    ) -> AMemCard | None:
        """Evolve an existing memory card with an updated conclusion, preserving provenance.

        Marks the previous version as superseded, creates a newer version inheriting
        active tags and structural links, and establishes an immutable lineage pointer.
        """
        old_card = self._cards.get(old_card_id)
        if not old_card:
            return None

        now = datetime.now(UTC)
        new_id = str(uuid.uuid4())[:8]
        combined_evidences = list(old_card.evidences)
        if new_evidences:
            combined_evidences.extend(new_evidences)

        new_card = AMemCard(
            id=new_id,
            title=title or old_card.title,
            conclusion=new_conclusion.strip(),
            evidences=combined_evidences,
            tags=set(old_card.tags),
            links=set(old_card.links),
            supersedes=old_card_id,
            version=old_card.version + 1,
            created_at=now,
            updated_at=now,
            metadata={
                **old_card.metadata,
                "evolution_reason": reason,
            },
        )

        old_card.superseded_by = new_id
        old_card.updated_at = now

        self.add_card(new_card)

        # Forward incoming links from old card to new card for graph continuity
        incoming = self._incoming_links.get(old_card_id, set())
        for inc_id in incoming:
            if inc_id in self._cards and inc_id != new_id:
                self._cards[inc_id].links.add(new_id)
                self._incoming_links[new_id].add(inc_id)

        return new_card

    def get_lineage(self, card_id: str) -> list[AMemCard]:
        """Trace the full ancestral and descendant evolution history of a card."""
        root = self._cards.get(card_id)
        if not root:
            return []

        # 1. Backtrack to origin ancestor
        history: deque[AMemCard] = deque([root])
        curr = root
        while curr.supersedes and curr.supersedes in self._cards:
            ancestor = self._cards[curr.supersedes]
            history.appendleft(ancestor)
            curr = ancestor

        # 2. Forward track to latest descendant
        curr = root
        while curr.superseded_by and curr.superseded_by in self._cards:
            descendant = self._cards[curr.superseded_by]
            history.append(descendant)
            curr = descendant

        return list(history)

    def get_active_cards(self) -> list[AMemCard]:
        """Return all cards currently not superseded."""
        return [c for c in self._cards.values() if c.is_active]

    def search_by_tag(self, tag: str, *, active_only: bool = True) -> list[AMemCard]:
        """Find cards associated with a specific tag."""
        card_ids = self._tag_index.get(tag, set())
        cards = [self._cards[cid] for cid in card_ids if cid in self._cards]
        if active_only:
            return [c for c in cards if c.is_active]
        return cards

    def traverse_subgraph(
        self,
        seed_ids: Sequence[str],
        *,
        max_depth: int = 2,
        active_only: bool = True,
    ) -> set[str]:
        """Breadth-first bidirectional graph traversal starting from seed cards."""
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque((sid, 0) for sid in seed_ids if sid in self._cards)

        while queue:
            cid, depth = queue.popleft()
            if cid in visited or depth > max_depth:
                continue

            card = self._cards[cid]
            if not active_only or card.is_active:
                visited.add(cid)

            if depth < max_depth:
                # Explore forward links
                for nxt in card.links:
                    if nxt not in visited and nxt in self._cards:
                        queue.append((nxt, depth + 1))
                # Explore incoming links
                for prev in self._incoming_links.get(cid, set()):
                    if prev not in visited and prev in self._cards:
                        queue.append((prev, depth + 1))

        return visited

    def export_digest(self, seed_ids: Sequence[str], *, max_depth: int = 1) -> str:
        """Export a cohesive Markdown knowledge digest of the related card cluster."""
        card_ids = self.traverse_subgraph(seed_ids, max_depth=max_depth, active_only=True)
        if not card_ids:
            return ""

        sorted_cards = sorted([self._cards[cid] for cid in card_ids], key=lambda c: c.title)
        blocks = [f"## Related Knowledge Cards ({len(sorted_cards)})"]
        for card in sorted_cards:
            blocks.append(card.render_markdown())
        return "\n\n".join(blocks)
