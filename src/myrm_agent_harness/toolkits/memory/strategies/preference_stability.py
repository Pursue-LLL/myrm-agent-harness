"""Preference stability detection strategy.

Manages user preference lifecycle through evidence accumulation, time decay,
and category-aware half-lives. Preferences graduate from Candidate → Provisional
→ Active as stability grows, and decay back to Dropped when stale.


[INPUT]
- memory.strategies.preference_stability_store::PreferenceFacetStoreProtocol (POS: preference facet storage protocol)

[OUTPUT]
- PreferenceCategory: Preference classification (6 categories with distinct half-lives)
- CueFamily: Signal source classification (3 tiers)
- PreferenceLifecycle: Lifecycle stage enum
- PreferenceFacet: Preference metadata record
- PreferenceCandidate: Incoming preference submission
- StabilityScorer: Score calculator with exponential decay + evidence accumulation
- PreferenceStabilityStrategy: Orchestrates micro-rebuild and full-rebuild cycles

[POS]
Preference stability strategy. Classifies preferences into categories with distinct
half-lives, accumulates evidence across sessions, resolves conflicts via argmax,
and enforces per-category budgets. Integrates with existing forgetting/maintenance
lifecycle without modifying the retrieval pipeline.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.strategies.preference_stability_store import (
        PreferenceFacetStoreProtocol,
    )

logger = logging.getLogger(__name__)


# ── Enums ───────────────────────────────────────────────────────────


class PreferenceCategory(StrEnum):
    """Preference classification with category-specific half-lives.

    Half-lives reflect natural stability: identity rarely changes,
    style preferences are ephemeral. Extensible via StrEnum.
    """

    IDENTITY = "identity"
    VETO = "veto"
    TOOLING = "tooling"
    GOAL = "goal"
    STYLE = "style"
    CHANNEL = "channel"


class CueFamily(StrEnum):
    """Signal source for preference evidence.

    Maps directly to existing preference_type in SemanticMemory:
    - EXPLICIT → preference_type="explicit"
    - IMPLICIT → preference_type="implicit"
    - INFERRED → regex/behavioral detection without explicit statement
    """

    EXPLICIT = "explicit"
    IMPLICIT = "implicit"
    INFERRED = "inferred"


class PreferenceLifecycle(StrEnum):
    """Preference lifecycle stage, controlled by stability score."""

    ACTIVE = "active"
    PROVISIONAL = "provisional"
    CANDIDATE = "candidate"
    DROPPED = "dropped"


# ── Constants ───────────────────────────────────────────────────────

HALF_LIFE_DAYS: dict[PreferenceCategory, float] = {
    PreferenceCategory.IDENTITY: 90.0,
    PreferenceCategory.VETO: 60.0,
    PreferenceCategory.TOOLING: 30.0,
    PreferenceCategory.GOAL: 30.0,
    PreferenceCategory.STYLE: 14.0,
    PreferenceCategory.CHANNEL: 7.0,
}

CUE_WEIGHT: dict[CueFamily, float] = {
    CueFamily.EXPLICIT: 1.0,
    CueFamily.IMPLICIT: 0.8,
    CueFamily.INFERRED: 0.6,
}

TAU_PROMOTE = 1.5
TAU_PROVISIONAL = 0.7
TAU_CANDIDATE = 0.4

CATEGORY_BUDGET: dict[PreferenceCategory, int] = {
    PreferenceCategory.IDENTITY: 5,
    PreferenceCategory.VETO: 5,
    PreferenceCategory.TOOLING: 5,
    PreferenceCategory.GOAL: 5,
    PreferenceCategory.STYLE: 3,
    PreferenceCategory.CHANNEL: 3,
}

EXPLICIT_EVIDENCE_MULTIPLIER = 2.0


# ── Data models ─────────────────────────────────────────────────────


@dataclass
class PreferenceFacet:
    """Metadata record for a tracked preference.

    Stored in SQLite preference_facets table. Links to SemanticMemory
    via memory_ids for content retrieval.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    key: str = ""
    value: str = ""
    category: PreferenceCategory = PreferenceCategory.STYLE
    cue: CueFamily = CueFamily.IMPLICIT
    lifecycle: PreferenceLifecycle = PreferenceLifecycle.CANDIDATE
    stability: float = 0.0
    evidence_count: int = 1
    memory_ids: list[str] = field(default_factory=list)
    first_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_pinned: bool = False
    user_forgotten: bool = False


@dataclass
class PreferenceCandidate:
    """Incoming preference submission from extractor.

    Submitted when a preference is detected in conversation. The stability
    strategy decides whether to create a new facet or accumulate evidence.
    """

    key: str
    value: str
    category: PreferenceCategory
    cue: CueFamily
    strength: float
    memory_id: str
    content: str = ""


# ── Scorer ──────────────────────────────────────────────────────────


class StabilityScorer:
    """Calculate preference stability score.

    Formula: stability = cue_weight × exp(-ln2×Δt/half_life) × ln(1 + evidence_count) × explicit_mult
    Where explicit_mult = 2.0 if cue is EXPLICIT (user stated preference directly), else 1.0.
    """

    @staticmethod
    def score(facet: PreferenceFacet) -> float:
        if facet.user_pinned:
            return float("inf")
        if facet.user_forgotten:
            return 0.0

        half_life = HALF_LIFE_DAYS.get(facet.category, 30.0)
        cue_weight = CUE_WEIGHT.get(facet.cue, 0.6)

        now = datetime.now(UTC)
        last_seen = facet.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        delta_days = max((now - last_seen).total_seconds() / 86400.0, 0.0)

        time_decay = math.exp(-math.log(2) * delta_days / half_life) if half_life > 0 else 1.0
        evidence_factor = math.log(1 + facet.evidence_count)
        explicit_mult = EXPLICIT_EVIDENCE_MULTIPLIER if facet.cue == CueFamily.EXPLICIT else 1.0

        return cue_weight * time_decay * evidence_factor * explicit_mult

    @staticmethod
    def classify(stability: float) -> PreferenceLifecycle:
        if stability >= TAU_PROMOTE:
            return PreferenceLifecycle.ACTIVE
        if stability >= TAU_PROVISIONAL:
            return PreferenceLifecycle.PROVISIONAL
        if stability >= TAU_CANDIDATE:
            return PreferenceLifecycle.CANDIDATE
        return PreferenceLifecycle.DROPPED


# ── Strategy ────────────────────────────────────────────────────────


class PreferenceStabilityStrategy:
    """Orchestrates preference lifecycle management.

    Two trigger points:
    - micro_rebuild: after session flush, processes new candidates only
    - full_rebuild: during maintenance cycle, recalculates all facets
    """

    def __init__(self, store: PreferenceFacetStoreProtocol) -> None:
        self._store = store

    async def submit_candidate(self, candidate: PreferenceCandidate) -> PreferenceFacet:
        """Submit a preference candidate. Merges with existing or creates new.

        When the same key already exists with a different value, the higher-stability
        value wins (argmax conflict resolution). The losing facet is demoted to Dropped.
        """
        existing = await self._store.find_by_key_value(candidate.key, candidate.value)

        if existing:
            existing.evidence_count += 1
            existing.last_seen = datetime.now(UTC)
            if not existing.memory_ids or candidate.memory_id not in existing.memory_ids:
                existing.memory_ids.append(candidate.memory_id)
            if CUE_WEIGHT.get(candidate.cue, 0) > CUE_WEIGHT.get(existing.cue, 0):
                existing.cue = candidate.cue
            existing.stability = StabilityScorer.score(existing)
            existing.lifecycle = StabilityScorer.classify(existing.stability)
            await self._store.upsert(existing)
            await self._resolve_key_conflicts(existing)
            return existing

        facet = PreferenceFacet(
            key=candidate.key,
            value=candidate.value,
            category=candidate.category,
            cue=candidate.cue,
            memory_ids=[candidate.memory_id],
        )
        facet.stability = StabilityScorer.score(facet)
        facet.lifecycle = StabilityScorer.classify(facet.stability)
        await self._store.upsert(facet)
        await self._resolve_key_conflicts(facet)
        return facet

    async def _resolve_key_conflicts(self, candidate_facet: PreferenceFacet) -> None:
        """Resolve value conflicts for the same key via argmax(stability).

        When multiple facets share the same key but different values, the one with
        highest stability wins. Losers are deleted.
        """
        siblings = await self._store.find_by_key(candidate_facet.key)
        if len(siblings) <= 1:
            return

        siblings.sort(key=lambda f: f.stability, reverse=True)
        winner = siblings[0]
        for loser in siblings[1:]:
            if loser.user_pinned:
                continue
            await self._store.delete(loser.id)
            logger.info(
                "Conflict resolution: dropped facet %s (%s=%s, stab=%.3f) in favor of %s=%s (stab=%.3f)",
                loser.id,
                loser.key,
                loser.value,
                loser.stability,
                winner.key,
                winner.value,
                winner.stability,
            )

    async def micro_rebuild(self) -> int:
        """Quick rebuild for new candidates after session flush.

        Only promotes strong explicit preferences to Active immediately.
        Returns number of promoted facets.
        """
        promoted = 0
        candidates = await self._store.list_by_lifecycle(PreferenceLifecycle.CANDIDATE)
        candidates.extend(await self._store.list_by_lifecycle(PreferenceLifecycle.PROVISIONAL))

        for facet in candidates:
            if facet.user_forgotten:
                continue
            new_stability = StabilityScorer.score(facet)
            new_lifecycle = StabilityScorer.classify(new_stability)
            if new_lifecycle != facet.lifecycle:
                facet.stability = new_stability
                facet.lifecycle = new_lifecycle
                await self._store.upsert(facet)
                if new_lifecycle == PreferenceLifecycle.ACTIVE:
                    promoted += 1

        if promoted:
            await self._enforce_budgets()

        return promoted

    async def full_rebuild(self) -> tuple[int, int, int]:
        """Full recalculation of all facets during maintenance.

        Returns (promoted, demoted, dropped) counts.
        """
        all_facets = await self._store.list_all()
        promoted, demoted, dropped = 0, 0, 0

        for facet in all_facets:
            if facet.user_pinned:
                continue
            if facet.user_forgotten:
                if facet.lifecycle != PreferenceLifecycle.DROPPED:
                    facet.lifecycle = PreferenceLifecycle.DROPPED
                    facet.stability = 0.0
                    await self._store.upsert(facet)
                    dropped += 1
                continue

            new_stability = StabilityScorer.score(facet)
            new_lifecycle = StabilityScorer.classify(new_stability)

            if new_lifecycle != facet.lifecycle:
                old_lifecycle = facet.lifecycle
                facet.stability = new_stability
                facet.lifecycle = new_lifecycle
                await self._store.upsert(facet)

                if _lifecycle_rank(new_lifecycle) > _lifecycle_rank(old_lifecycle):
                    promoted += 1
                else:
                    if new_lifecycle == PreferenceLifecycle.DROPPED:
                        dropped += 1
                    else:
                        demoted += 1
            elif facet.stability != new_stability:
                facet.stability = new_stability
                await self._store.upsert(facet)

        await self._enforce_budgets()
        await self._store.cleanup_dropped()

        return promoted, demoted, dropped

    async def get_active_preferences(self) -> list[PreferenceFacet]:
        """Return all Active preferences for context injection."""
        return await self._store.list_by_lifecycle(PreferenceLifecycle.ACTIVE)

    async def close(self) -> None:
        """Release storage resources."""
        await self._store.close()

    async def _enforce_budgets(self) -> None:
        """Enforce per-category budgets by demoting lowest-stability Active facets."""
        active = await self._store.list_by_lifecycle(PreferenceLifecycle.ACTIVE)

        by_category: dict[PreferenceCategory, list[PreferenceFacet]] = {}
        for facet in active:
            by_category.setdefault(facet.category, []).append(facet)

        for category, facets in by_category.items():
            budget = CATEGORY_BUDGET.get(category, 5)
            if len(facets) <= budget:
                continue
            facets.sort(key=lambda f: f.stability, reverse=True)
            for excess in facets[budget:]:
                excess.lifecycle = PreferenceLifecycle.PROVISIONAL
                excess.stability = StabilityScorer.score(excess)
                await self._store.upsert(excess)
                logger.info(
                    "Budget enforcement: demoted facet %s (%s=%s) from Active to Provisional",
                    excess.id,
                    excess.key,
                    excess.value,
                )


def _lifecycle_rank(lifecycle: PreferenceLifecycle) -> int:
    return {
        PreferenceLifecycle.DROPPED: 0,
        PreferenceLifecycle.CANDIDATE: 1,
        PreferenceLifecycle.PROVISIONAL: 2,
        PreferenceLifecycle.ACTIVE: 3,
    }.get(lifecycle, 0)
