"""Store implementation for PersonCard and relationship profiles.

[INPUT] PersonCard entities, lookup queries, merge requests, and decay evaluation timestamps.
[OUTPUT] Persisted PersonCard collections, updated decay statuses, and unified profiles.
[POS] Harness framework toolkit memory store layer for personal entity cards.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from myrm_agent_harness.toolkits.memory.person_card.models import (
    PersonCard,
    RelationType,
)
from myrm_agent_harness.toolkits.memory.strategies.gravity_decay import (
    compute_gravity_decay,
)


class PersonCardStore:
    """In-memory and file-backed store for managing personal relationship cards."""

    def __init__(self, storage_path: Path | str | None = None) -> None:
        self._storage_path: Path | None = (
            Path(storage_path) if storage_path is not None else None
        )
        self._cards: dict[str, PersonCard] = {}
        if self._storage_path is not None and self._storage_path.exists():
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        try:
            content = self._storage_path.read_text(encoding="utf-8")
            if not content.strip():
                return
            data = json.loads(content)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        card = PersonCard.model_validate(item)
                        self._cards[card.person_id] = card
        except Exception:
            # Fallback gracefully if corrupted or unreadable
            pass

    def _save_to_disk(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = [card.model_dump() for card in self._cards.values()]
        self._storage_path.write_text(
            json.dumps(serialized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save_person(self, card: PersonCard) -> PersonCard:
        """Create or update a person card and persist to disk if configured."""
        self._cards[card.person_id] = card
        self._save_to_disk()
        return card

    def get_person(self, person_id: str) -> PersonCard | None:
        """Fetch a person card by person_id."""
        return self._cards.get(person_id)

    def delete_person(self, person_id: str) -> bool:
        """Remove a person card by person_id."""
        if person_id in self._cards:
            del self._cards[person_id]
            self._save_to_disk()
            return True
        return False

    def list_persons(
        self,
        scope: Literal["global", "agent"] | None = None,
        relation_type: RelationType | None = None,
        include_weak: bool = True,
        include_archived: bool = False,
        agent_id: str | None = None,
    ) -> list[PersonCard]:
        """List person cards matching given filters."""
        results: list[PersonCard] = []
        for card in self._cards.values():
            if not include_archived and card.decay_status == "archived":
                continue
            if not include_weak and card.decay_status == "weak":
                continue
            if scope is not None and card.scope != scope:
                continue
            if relation_type is not None and card.relation_type != relation_type:
                continue
            if card.scope == "agent" and agent_id is not None and card.agent_id != agent_id:
                continue
            results.append(card)
        return results

    def find_by_name_or_alias(
        self,
        query: str,
        agent_id: str | None = None,
        include_weak: bool = True,
    ) -> list[PersonCard]:
        """Find person cards matching display_name or aliases case-insensitively."""
        normalized = query.strip().lower()
        if not normalized:
            return []

        matched: list[PersonCard] = []
        for card in self._cards.values():
            if card.decay_status == "archived":
                continue
            if not include_weak and card.decay_status == "weak":
                continue
            if card.scope == "agent" and agent_id is not None and card.agent_id != agent_id:
                continue

            names = [card.display_name.lower()] + [a.lower() for a in card.aliases]
            if normalized in names or any(normalized in n or n in normalized for n in names):
                matched.append(card)

        # Sort exact matches first, then active before weak
        matched.sort(
            key=lambda c: (
                c.display_name.lower() != normalized,
                normalized not in [a.lower() for a in c.aliases],
                c.decay_status == "weak",
            )
        )
        return matched

    def refresh_decay(
        self,
        now: datetime | None = None,
        weak_threshold: float = 0.3,
    ) -> dict[str, float]:
        """Recalculate continuous-time gravity decay for all cards and mark weak items."""
        updated_scores: dict[str, float] = {}
        for card in self._cards.values():
            if card.decay_status == "archived":
                continue
            ts = card.last_interaction_at
            score = compute_gravity_decay(
                created_at=ts,
                now=now,
                interactions=len(card.interaction_timeline),
                quality_score=card.confidence,
            )
            card.decay_score = float(score)
            updated_scores[card.person_id] = float(score)

            if score < weak_threshold and card.decay_status == "active":
                card.decay_status = "weak"
            elif score >= weak_threshold and card.decay_status == "weak":
                card.decay_status = "active"

        self._save_to_disk()
        return updated_scores

    def merge_persons(self, source_id: str, target_id: str) -> PersonCard:
        """Merge source person card into target card, archiving source."""
        source = self._cards.get(source_id)
        target = self._cards.get(target_id)
        if source is None:
            raise ValueError(f"Source person card {source_id} not found")
        if target is None:
            raise ValueError(f"Target person card {target_id} not found")

        # Merge aliases
        combined_aliases = set(target.aliases)
        combined_aliases.add(source.display_name)
        combined_aliases.update(source.aliases)
        if target.display_name in combined_aliases:
            combined_aliases.remove(target.display_name)
        target.aliases = sorted(list(combined_aliases))

        # Merge attributes
        target_dietary = set(target.attributes.dietary_restrictions)
        target_dietary.update(source.attributes.dietary_restrictions)
        target.attributes.dietary_restrictions = sorted(list(target_dietary))

        if not target.attributes.birthday and source.attributes.birthday:
            target.attributes.birthday = source.attributes.birthday
        if not target.attributes.timezone and source.attributes.timezone:
            target.attributes.timezone = source.attributes.timezone
        if (
            not target.attributes.preferred_contact_hours
            and source.attributes.preferred_contact_hours
        ):
            target.attributes.preferred_contact_hours = (
                source.attributes.preferred_contact_hours
            )
        if (
            not target.attributes.approval_preference
            and source.attributes.approval_preference
        ):
            target.attributes.approval_preference = (
                source.attributes.approval_preference
            )

        for k, v in source.attributes.custom_notes.items():
            if k not in target.attributes.custom_notes:
                target.attributes.custom_notes[k] = v

        # Merge commitments
        commitments_set = set(target.commitments)
        commitments_set.update(source.commitments)
        target.commitments = sorted(list(commitments_set))

        # Merge timeline
        combined_timeline = list(target.interaction_timeline) + list(
            source.interaction_timeline
        )
        combined_timeline.sort(key=lambda item: item.timestamp)
        target.interaction_timeline = combined_timeline

        # Update last interaction
        if source.last_interaction_at and (
            not target.last_interaction_at
            or source.last_interaction_at > target.last_interaction_at
        ):
            target.last_interaction_at = source.last_interaction_at

        # Mark source as archived
        source.decay_status = "archived"
        self._cards[source_id] = source
        self._cards[target_id] = target
        self._save_to_disk()
        return target
