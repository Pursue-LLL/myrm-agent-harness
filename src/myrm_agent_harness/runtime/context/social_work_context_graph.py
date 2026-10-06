"""Social Collaboration Graph and Cross-Application Work Context Engine.

Resolves human collaboration roles, decision chains, multi-modal cross-app work assets,
temporal-semantic fuzzy inquiries, and transparent privacy boundaries.
"""

from __future__ import annotations

import time

from myrm_agent_harness.runtime.context.social_work_context_graph_types import (
    CrossAppWorkAsset,
    FuzzyQueryIntent,
    PersonEntity,
    PersonRoleKind,
    PrivacyAuditRecord,
    ResolvedContextAnchor,
    WorkAssetKind,
)

__all__ = [
    "CrossAppChronologicalResolver",
    "CrossAppWorkAsset",
    "FuzzyQueryIntent",
    "PersonEntity",
    "PersonRoleKind",
    "PrivacyAuditRecord",
    "PrivacyAuditSentinel",
    "ResolvedContextAnchor",
    "SocialCollaborationGraph",
    "WorkAssetKind",
]


class SocialCollaborationGraph:
    """Maintains team social structure, aliases, decision roles, and delegation chains."""

    def __init__(self) -> None:
        self._people: dict[str, PersonEntity] = {}
        self._alias_map: dict[str, str] = {}
        self._reporting_tree: dict[str, set[str]] = {}

    def register_person(self, person: PersonEntity) -> None:
        """Enrolls a collaborator persona with case-insensitive alias lookups."""
        self._people[person.person_id] = person
        self._alias_map[person.name.lower()] = person.person_id
        for alias in person.aliases:
            self._alias_map[alias.lower()] = person.person_id

    def get_person(self, person_id: str) -> PersonEntity | None:
        return self._people.get(person_id)

    def resolve_person_mention(self, mention: str) -> PersonEntity | None:
        """Resolves informal references ('王总', '老张', 'Alice') to canonical identity."""
        cleaned = mention.strip().lower()
        person_id = self._alias_map.get(cleaned)
        if person_id:
            return self._people.get(person_id)
        # Substring alias search
        for alias_key, pid in self._alias_map.items():
            if alias_key in cleaned or cleaned in alias_key:
                return self._people.get(pid)
        return None

    def link_reporting_line(self, leader_id: str, member_id: str) -> None:
        """Registers hierarchical authority for organizational decision flows."""
        if leader_id not in self._reporting_tree:
            self._reporting_tree[leader_id] = set()
        self._reporting_tree[leader_id].add(member_id)

    def is_decision_maker(self, person_id: str) -> bool:
        person = self._people.get(person_id)
        if not person:
            return False
        return person.role_kind in (PersonRoleKind.LEADER, PersonRoleKind.DECISION_MAKER)


class CrossAppChronologicalResolver:
    """Performs multi-dimensional temporal and semantic fuzzy resolution across apps."""

    def __init__(self) -> None:
        self._assets: dict[str, CrossAppWorkAsset] = {}

    def register_asset(self, asset: CrossAppWorkAsset) -> None:
        self._assets[asset.asset_id] = asset

    def get_asset(self, asset_id: str) -> CrossAppWorkAsset | None:
        return self._assets.get(asset_id)

    def resolve_fuzzy_query(
        self,
        intent: FuzzyQueryIntent,
        graph: SocialCollaborationGraph,
        *,
        current_time_epoch_s: float | None = None,
    ) -> ResolvedContextAnchor:
        """Resolves fuzzy queries combining person mentions, timeframes, and keywords."""
        now = current_time_epoch_s if current_time_epoch_s is not None else time.time()
        matched_person: PersonEntity | None = None
        if intent.mention_person:
            matched_person = graph.resolve_person_mention(intent.mention_person)

        # 1. Temporal filter window
        max_age_seconds: float = float("inf")
        if intent.time_hint == "recent" or intent.time_hint == "last_week":
            max_age_seconds = 7 * 86400.0
        elif intent.time_hint == "past_month":
            max_age_seconds = 30 * 86400.0

        candidates: list[tuple[CrossAppWorkAsset, float]] = []

        for asset in self._assets.values():
            score = 0.0

            # Filter by person if matched
            if matched_person is not None:
                if asset.created_by_person_id == matched_person.person_id:
                    score += 0.5
                else:
                    continue  # Strict authorship filter when specific person mentioned
            else:
                score += 0.1

            # Timeframe check
            age = now - asset.timestamp_epoch_s
            if age > max_age_seconds:
                continue
            if age <= 7 * 86400.0:
                score += 0.2

            # Keyword relevance in title and summary
            for kw in intent.keyword_hints:
                kw_low = kw.lower()
                if kw_low in asset.title.lower():
                    score += 0.25
                if kw_low in asset.semantic_summary.lower():
                    score += 0.15

            if score > 0.2:
                candidates.append((asset, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        matched_assets = tuple(item[0] for item in candidates[:5])

        if not matched_assets:
            return ResolvedContextAnchor(
                matched_person=matched_person,
                matched_assets=(),
                confidence_score=0.0,
                explanation="No cross-application assets matching criteria found.",
            )

        top_score = min(candidates[0][1], 1.0)
        person_desc = f" linked to '{matched_person.name}'" if matched_person else ""
        expl = f"Discovered {len(matched_assets)} assets{person_desc} with top score {top_score:.2f}."

        return ResolvedContextAnchor(
            matched_person=matched_person,
            matched_assets=matched_assets,
            confidence_score=round(top_score, 2),
            explanation=expl,
        )


class PrivacyAuditSentinel:
    """Enforces directory/source authorization boundaries with complete audit logging."""

    def __init__(self, allowed_prefixes: tuple[str, ...]) -> None:
        self._allowed_prefixes = allowed_prefixes
        self._records: list[PrivacyAuditRecord] = []

    def check_and_audit(self, *, action: str, target_path: str, timestamp_utc: str) -> PrivacyAuditRecord:
        """Verifies if target path complies with authorization boundary."""
        is_allowed = any(target_path.startswith(prefix) for prefix in self._allowed_prefixes)
        record = PrivacyAuditRecord(
            access_id=f"audit_{len(self._records) + 1}",
            action=action,
            queried_target=target_path,
            is_authorized=is_allowed,
            timestamp_utc=timestamp_utc,
        )
        self._records.append(record)
        return record

    def get_audit_records(self) -> tuple[PrivacyAuditRecord, ...]:
        return tuple(self._records)
