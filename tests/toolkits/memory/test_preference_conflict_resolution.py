"""Integration tests for preference stability conflict resolution.

Tests the argmax-based conflict resolution strategy that:
- keep_new: Higher stability wins (data-driven, not hardcoded)
- keep_old: user_pinned facets survive regardless of stability
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.strategies.preference_stability import (
    CueFamily,
    PreferenceCandidate,
    PreferenceCategory,
    PreferenceFacet,
    PreferenceLifecycle,
    PreferenceStabilityStrategy,
    StabilityScorer,
)


class InMemoryPreferenceFacetStore:
    """In-memory store for testing without SQLite dependency."""

    def __init__(self) -> None:
        self._facets: dict[str, PreferenceFacet] = {}

    async def upsert(self, facet: PreferenceFacet) -> None:
        self._facets[facet.id] = facet

    async def find_by_id(self, facet_id: str) -> PreferenceFacet | None:
        return self._facets.get(facet_id)

    async def find_by_key_value(self, key: str, value: str) -> PreferenceFacet | None:
        for facet in self._facets.values():
            if facet.key == key and facet.value == value:
                return facet
        return None

    async def find_by_key(self, key: str) -> list[PreferenceFacet]:
        return [f for f in self._facets.values() if f.key == key]

    async def list_by_lifecycle(self, lifecycle: PreferenceLifecycle) -> list[PreferenceFacet]:
        return [f for f in self._facets.values() if f.lifecycle == lifecycle]

    async def list_all(self) -> list[PreferenceFacet]:
        return list(self._facets.values())

    async def cleanup_dropped(self, max_age_days: int = 30) -> int:
        to_remove = [
            fid
            for fid, f in self._facets.items()
            if f.lifecycle == PreferenceLifecycle.DROPPED
        ]
        for fid in to_remove:
            del self._facets[fid]
        return len(to_remove)

    async def delete(self, facet_id: str) -> None:
        self._facets.pop(facet_id, None)

    async def close(self) -> None:
        pass


@pytest.fixture
def store() -> InMemoryPreferenceFacetStore:
    return InMemoryPreferenceFacetStore()


@pytest.fixture
def strategy(store: InMemoryPreferenceFacetStore) -> PreferenceStabilityStrategy:
    return PreferenceStabilityStrategy(store)


class TestResolveKeyConflicts:
    """Tests preference conflict resolution via argmax(stability)."""

    @pytest.mark.asyncio
    async def test_higher_stability_wins(
        self, store: InMemoryPreferenceFacetStore, strategy: PreferenceStabilityStrategy
    ) -> None:
        """New submission with higher stability replaces old one (keep_new equivalent)."""
        old_facet = PreferenceFacet(
            id="old",
            key="preferred_language",
            value="Python",
            category=PreferenceCategory.TOOLING,
            cue=CueFamily.IMPLICIT,
            evidence_count=1,
            last_seen=datetime.now(UTC) - timedelta(days=60),
        )
        old_facet.stability = StabilityScorer.score(old_facet)
        await store.upsert(old_facet)

        new_candidate = PreferenceCandidate(
            key="preferred_language",
            value="Rust",
            category=PreferenceCategory.TOOLING,
            cue=CueFamily.EXPLICIT,
            strength=0.9,
            memory_id="mem-001",
        )
        result = await strategy.submit_candidate(new_candidate)

        remaining = await store.find_by_key("preferred_language")
        assert len(remaining) == 1
        assert remaining[0].value == "Rust"
        assert result.value == "Rust"

    @pytest.mark.asyncio
    async def test_lower_stability_loses(
        self, store: InMemoryPreferenceFacetStore, strategy: PreferenceStabilityStrategy
    ) -> None:
        """Existing high-stability facet survives against weak new candidate (keep_old equivalent)."""
        strong_facet = PreferenceFacet(
            id="strong",
            key="editor",
            value="VSCode",
            category=PreferenceCategory.TOOLING,
            cue=CueFamily.EXPLICIT,
            evidence_count=10,
            last_seen=datetime.now(UTC),
        )
        strong_facet.stability = StabilityScorer.score(strong_facet)
        await store.upsert(strong_facet)

        weak_candidate = PreferenceCandidate(
            key="editor",
            value="Nano",
            category=PreferenceCategory.TOOLING,
            cue=CueFamily.IMPLICIT,
            strength=0.3,
            memory_id="mem-002",
        )
        await strategy.submit_candidate(weak_candidate)

        remaining = await store.find_by_key("editor")
        assert len(remaining) == 1
        assert remaining[0].value == "VSCode"

    @pytest.mark.asyncio
    async def test_user_pinned_survives_higher_stability(
        self, store: InMemoryPreferenceFacetStore, strategy: PreferenceStabilityStrategy
    ) -> None:
        """User-pinned facets are never deleted regardless of stability (governance override)."""
        pinned_facet = PreferenceFacet(
            id="pinned",
            key="theme",
            value="dark",
            category=PreferenceCategory.STYLE,
            cue=CueFamily.IMPLICIT,
            evidence_count=1,
            user_pinned=True,
            last_seen=datetime.now(UTC) - timedelta(days=365),
        )
        pinned_facet.stability = StabilityScorer.score(pinned_facet)
        await store.upsert(pinned_facet)

        new_candidate = PreferenceCandidate(
            key="theme",
            value="light",
            category=PreferenceCategory.STYLE,
            cue=CueFamily.EXPLICIT,
            strength=0.95,
            memory_id="mem-003",
        )
        await strategy.submit_candidate(new_candidate)

        remaining = await store.find_by_key("theme")
        values = {f.value for f in remaining}
        assert "dark" in values

    @pytest.mark.asyncio
    async def test_same_value_accumulates_evidence(
        self, store: InMemoryPreferenceFacetStore, strategy: PreferenceStabilityStrategy
    ) -> None:
        """Same key+value submission accumulates evidence (strengthens, no conflict)."""
        candidate1 = PreferenceCandidate(
            key="indent",
            value="4 spaces",
            category=PreferenceCategory.STYLE,
            cue=CueFamily.EXPLICIT,
            strength=0.8,
            memory_id="mem-a",
        )
        await strategy.submit_candidate(candidate1)

        candidate2 = PreferenceCandidate(
            key="indent",
            value="4 spaces",
            category=PreferenceCategory.STYLE,
            cue=CueFamily.EXPLICIT,
            strength=0.8,
            memory_id="mem-b",
        )
        result = await strategy.submit_candidate(candidate2)

        assert result.evidence_count == 2
        assert "mem-a" in result.memory_ids
        assert "mem-b" in result.memory_ids

    @pytest.mark.asyncio
    async def test_three_way_conflict_strongest_wins(
        self, store: InMemoryPreferenceFacetStore, strategy: PreferenceStabilityStrategy
    ) -> None:
        """Among 3 competing values for same key, strongest survives."""
        for value, evidence, age_days in [
            ("tabs", 2, 30),
            ("2 spaces", 1, 5),
            ("4 spaces", 8, 1),
        ]:
            facet = PreferenceFacet(
                key="indent_style",
                value=value,
                category=PreferenceCategory.STYLE,
                cue=CueFamily.EXPLICIT,
                evidence_count=evidence,
                last_seen=datetime.now(UTC) - timedelta(days=age_days),
            )
            facet.stability = StabilityScorer.score(facet)
            await store.upsert(facet)

        trigger = PreferenceCandidate(
            key="indent_style",
            value="4 spaces",
            category=PreferenceCategory.STYLE,
            cue=CueFamily.EXPLICIT,
            strength=0.9,
            memory_id="mem-trigger",
        )
        await strategy.submit_candidate(trigger)

        remaining = await store.find_by_key("indent_style")
        assert len(remaining) == 1
        assert remaining[0].value == "4 spaces"


class TestStabilityScorer:
    """Tests for stability score calculation."""

    def test_pinned_infinite_stability(self) -> None:
        facet = PreferenceFacet(key="k", value="v", user_pinned=True)
        assert StabilityScorer.score(facet) == float("inf")

    def test_forgotten_zero_stability(self) -> None:
        facet = PreferenceFacet(key="k", value="v", user_forgotten=True)
        assert StabilityScorer.score(facet) == 0.0

    def test_explicit_cue_higher_than_implicit(self) -> None:
        base_kwargs = {
            "key": "test",
            "value": "v",
            "category": PreferenceCategory.TOOLING,
            "evidence_count": 3,
            "last_seen": datetime.now(UTC),
        }
        explicit = PreferenceFacet(**base_kwargs, cue=CueFamily.EXPLICIT)
        implicit = PreferenceFacet(**base_kwargs, cue=CueFamily.IMPLICIT)
        assert StabilityScorer.score(explicit) > StabilityScorer.score(implicit)

    def test_more_evidence_higher_stability(self) -> None:
        kwargs = {
            "key": "test",
            "value": "v",
            "category": PreferenceCategory.STYLE,
            "cue": CueFamily.EXPLICIT,
            "last_seen": datetime.now(UTC),
        }
        few = PreferenceFacet(**kwargs, evidence_count=1)
        many = PreferenceFacet(**kwargs, evidence_count=10)
        assert StabilityScorer.score(many) > StabilityScorer.score(few)

    def test_recent_higher_than_old(self) -> None:
        kwargs = {
            "key": "test",
            "value": "v",
            "category": PreferenceCategory.STYLE,
            "cue": CueFamily.EXPLICIT,
            "evidence_count": 3,
        }
        recent = PreferenceFacet(**kwargs, last_seen=datetime.now(UTC))
        old = PreferenceFacet(**kwargs, last_seen=datetime.now(UTC) - timedelta(days=180))
        assert StabilityScorer.score(recent) > StabilityScorer.score(old)

    def test_identity_category_more_stable(self) -> None:
        """IDENTITY has longer half-life (365d) vs STYLE (14d)."""
        kwargs = {
            "key": "test",
            "value": "v",
            "cue": CueFamily.EXPLICIT,
            "evidence_count": 3,
            "last_seen": datetime.now(UTC) - timedelta(days=30),
        }
        identity = PreferenceFacet(**kwargs, category=PreferenceCategory.IDENTITY)
        style = PreferenceFacet(**kwargs, category=PreferenceCategory.STYLE)
        assert StabilityScorer.score(identity) > StabilityScorer.score(style)
