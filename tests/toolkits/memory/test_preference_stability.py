"""Tests for preference stability detection strategy.

Covers:
- StabilityScorer formula correctness
- Lifecycle classification thresholds
- PreferenceStabilityStrategy: submit, merge, micro/full rebuild
- SQLitePreferenceFacetStore: CRUD, lifecycle query, cleanup
- Category budget enforcement
- Pin/forget user overrides
- Time decay behavior
- Conflict resolution via argmax
- _infer_preference_category priority order
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.strategies.preference_stability import (
    CATEGORY_BUDGET,
    TAU_CANDIDATE,
    TAU_PROMOTE,
    TAU_PROVISIONAL,
    CueFamily,
    PreferenceCandidate,
    PreferenceCategory,
    PreferenceFacet,
    PreferenceLifecycle,
    PreferenceStabilityStrategy,
    StabilityScorer,
)
from myrm_agent_harness.toolkits.memory.strategies.preference_stability_store import (
    SQLitePreferenceFacetStore,
)

# ── Scorer Tests ─────────────────────────────────────────────────────


class TestStabilityScorer:
    def test_fresh_explicit_score(self) -> None:
        """Single explicit mention: cue_weight(1.0) × exp(0) × ln(2) × explicit_mult(2.0) ≈ 1.386"""
        facet = PreferenceFacet(
            key="python",
            value="I like Python",
            cue=CueFamily.EXPLICIT,
            evidence_count=1,
            last_seen=datetime.now(UTC),
        )
        score = StabilityScorer.score(facet)
        expected = 1.0 * math.log(2) * 2.0
        assert abs(score - expected) < 0.01

    def test_evidence_accumulation(self) -> None:
        """More evidence → higher score: ln(1+5) > ln(1+1)"""
        facet_1 = PreferenceFacet(evidence_count=1, last_seen=datetime.now(UTC))
        facet_5 = PreferenceFacet(evidence_count=5, last_seen=datetime.now(UTC))
        assert StabilityScorer.score(facet_5) > StabilityScorer.score(facet_1)

    def test_time_decay(self) -> None:
        """Score decays with age. Style half-life = 14 days → half at 14 days."""
        now = datetime.now(UTC)
        fresh = PreferenceFacet(
            category=PreferenceCategory.STYLE,
            evidence_count=3,
            last_seen=now,
        )
        stale = PreferenceFacet(
            category=PreferenceCategory.STYLE,
            evidence_count=3,
            last_seen=now - timedelta(days=14),
        )
        fresh_score = StabilityScorer.score(fresh)
        stale_score = StabilityScorer.score(stale)
        assert abs(stale_score / fresh_score - 0.5) < 0.02

    def test_identity_decays_slower_than_style(self) -> None:
        """Identity (90-day half-life) retains more value than Style (14-day) after 30 days."""
        now = datetime.now(UTC)
        identity = PreferenceFacet(
            category=PreferenceCategory.IDENTITY,
            evidence_count=3,
            last_seen=now - timedelta(days=30),
        )
        style = PreferenceFacet(
            category=PreferenceCategory.STYLE,
            evidence_count=3,
            last_seen=now - timedelta(days=30),
        )
        assert StabilityScorer.score(identity) > StabilityScorer.score(style)

    def test_pinned_infinite(self) -> None:
        facet = PreferenceFacet(user_pinned=True)
        assert StabilityScorer.score(facet) == float("inf")

    def test_forgotten_zero(self) -> None:
        facet = PreferenceFacet(user_forgotten=True)
        assert StabilityScorer.score(facet) == 0.0

    def test_cue_weight_ordering(self) -> None:
        """Explicit > Implicit > Inferred"""
        now = datetime.now(UTC)
        explicit = PreferenceFacet(
            cue=CueFamily.EXPLICIT, evidence_count=1, last_seen=now
        )
        implicit = PreferenceFacet(
            cue=CueFamily.IMPLICIT, evidence_count=1, last_seen=now
        )
        inferred = PreferenceFacet(
            cue=CueFamily.INFERRED, evidence_count=1, last_seen=now
        )
        assert (
            StabilityScorer.score(explicit)
            > StabilityScorer.score(implicit)
            > StabilityScorer.score(inferred)
        )

    def test_classify_thresholds(self) -> None:
        assert StabilityScorer.classify(2.0) == PreferenceLifecycle.ACTIVE
        assert StabilityScorer.classify(TAU_PROMOTE) == PreferenceLifecycle.ACTIVE
        assert StabilityScorer.classify(1.0) == PreferenceLifecycle.PROVISIONAL
        assert (
            StabilityScorer.classify(TAU_PROVISIONAL) == PreferenceLifecycle.PROVISIONAL
        )
        assert StabilityScorer.classify(0.5) == PreferenceLifecycle.CANDIDATE
        assert StabilityScorer.classify(TAU_CANDIDATE) == PreferenceLifecycle.CANDIDATE
        assert StabilityScorer.classify(0.2) == PreferenceLifecycle.DROPPED


# ── Store Tests ──────────────────────────────────────────────────────


@pytest.fixture
def store_path(tmp_path):
    return str(tmp_path / "test_prefs.db")


class TestSQLitePreferenceFacetStore:
    @pytest.mark.asyncio
    async def test_upsert_and_find(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        facet = PreferenceFacet(
            id="f1", key="lang", value="Python", category=PreferenceCategory.TOOLING
        )
        await store.upsert(facet)
        found = await store.find_by_key_value("lang", "Python")
        assert found is not None
        assert found.id == "f1"
        assert found.category == PreferenceCategory.TOOLING
        await store.close()

    @pytest.mark.asyncio
    async def test_find_returns_none(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        assert await store.find_by_key_value("x", "y") is None
        await store.close()

    @pytest.mark.asyncio
    async def test_list_by_lifecycle(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        active = PreferenceFacet(
            id="a1",
            key="k1",
            value="v1",
            lifecycle=PreferenceLifecycle.ACTIVE,
            stability=2.0,
        )
        candidate = PreferenceFacet(
            id="c1",
            key="k2",
            value="v2",
            lifecycle=PreferenceLifecycle.CANDIDATE,
            stability=0.5,
        )
        await store.upsert(active)
        await store.upsert(candidate)
        actives = await store.list_by_lifecycle(PreferenceLifecycle.ACTIVE)
        assert len(actives) == 1
        assert actives[0].id == "a1"
        await store.close()

    @pytest.mark.asyncio
    async def test_list_all(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        for i in range(3):
            await store.upsert(PreferenceFacet(id=f"f{i}", key=f"k{i}", value=f"v{i}"))
        all_facets = await store.list_all()
        assert len(all_facets) == 3
        await store.close()

    @pytest.mark.asyncio
    async def test_upsert_update(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        facet = PreferenceFacet(id="u1", key="k", value="v", evidence_count=1)
        await store.upsert(facet)
        facet.evidence_count = 5
        facet.stability = 2.0
        await store.upsert(facet)
        found = await store.find_by_key_value("k", "v")
        assert found is not None
        assert found.evidence_count == 5
        assert found.stability == 2.0
        await store.close()

    @pytest.mark.asyncio
    async def test_cleanup_dropped(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        old = PreferenceFacet(
            id="old1",
            key="k",
            value="v",
            lifecycle=PreferenceLifecycle.DROPPED,
            last_seen=datetime.now(UTC) - timedelta(days=60),
        )
        await store.upsert(old)
        removed = await store.cleanup_dropped(max_age_days=30)
        assert removed >= 1
        assert await store.find_by_key_value("k", "v") is None
        await store.close()


# ── Strategy Tests ───────────────────────────────────────────────────


class TestPreferenceStabilityStrategy:
    @pytest.mark.asyncio
    async def test_submit_creates_new(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        strategy = PreferenceStabilityStrategy(store)
        candidate = PreferenceCandidate(
            key="style",
            value="I prefer concise responses",
            category=PreferenceCategory.STYLE,
            cue=CueFamily.EXPLICIT,
            strength=0.8,
            memory_id="mem1",
        )
        facet = await strategy.submit_candidate(candidate)
        assert facet.evidence_count == 1
        assert facet.memory_ids == ["mem1"]
        assert facet.stability > 0
        await store.close()

    @pytest.mark.asyncio
    async def test_submit_merges_existing(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        strategy = PreferenceStabilityStrategy(store)
        c1 = PreferenceCandidate(
            key="style",
            value="I prefer concise responses",
            category=PreferenceCategory.STYLE,
            cue=CueFamily.IMPLICIT,
            strength=0.5,
            memory_id="m1",
        )
        c2 = PreferenceCandidate(
            key="style",
            value="I prefer concise responses",
            category=PreferenceCategory.STYLE,
            cue=CueFamily.EXPLICIT,
            strength=0.8,
            memory_id="m2",
        )
        await strategy.submit_candidate(c1)
        facet = await strategy.submit_candidate(c2)
        assert facet.evidence_count == 2
        assert set(facet.memory_ids) == {"m1", "m2"}
        assert facet.cue == CueFamily.EXPLICIT
        await store.close()

    @pytest.mark.asyncio
    async def test_micro_rebuild_promotes(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        strategy = PreferenceStabilityStrategy(store)
        for i in range(5):
            await strategy.submit_candidate(
                PreferenceCandidate(
                    key="lang",
                    value="Python is great",
                    category=PreferenceCategory.TOOLING,
                    cue=CueFamily.EXPLICIT,
                    strength=0.9,
                    memory_id=f"m{i}",
                )
            )
        await strategy.micro_rebuild()
        active = await strategy.get_active_preferences()
        assert len(active) >= 1
        assert active[0].key == "lang"
        await store.close()

    @pytest.mark.asyncio
    async def test_full_rebuild_demotes_stale(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        strategy = PreferenceStabilityStrategy(store)
        stale_facet = PreferenceFacet(
            id="stale1",
            key="old",
            value="old pref",
            category=PreferenceCategory.STYLE,
            lifecycle=PreferenceLifecycle.ACTIVE,
            stability=2.0,
            evidence_count=2,
            last_seen=datetime.now(UTC) - timedelta(days=20),
        )
        await store.upsert(stale_facet)
        _promoted, _demoted, _dropped = await strategy.full_rebuild()
        updated = await store.find_by_key_value("old", "old pref")
        assert updated is not None
        assert updated.lifecycle != PreferenceLifecycle.ACTIVE
        await store.close()

    @pytest.mark.asyncio
    async def test_budget_enforcement(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        strategy = PreferenceStabilityStrategy(store)
        budget = CATEGORY_BUDGET[PreferenceCategory.STYLE]
        for i in range(budget + 3):
            facet = PreferenceFacet(
                id=f"s{i}",
                key=f"style{i}",
                value=f"pref{i}",
                category=PreferenceCategory.STYLE,
                lifecycle=PreferenceLifecycle.ACTIVE,
                stability=2.0 + i * 0.1,
                evidence_count=5,
                last_seen=datetime.now(UTC),
            )
            await store.upsert(facet)
        await strategy._enforce_budgets()
        active = await store.list_by_lifecycle(PreferenceLifecycle.ACTIVE)
        style_active = [f for f in active if f.category == PreferenceCategory.STYLE]
        assert len(style_active) <= budget
        await store.close()

    @pytest.mark.asyncio
    async def test_forgotten_stays_dropped(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        strategy = PreferenceStabilityStrategy(store)
        facet = PreferenceFacet(
            id="fg1",
            key="bad",
            value="disliked",
            lifecycle=PreferenceLifecycle.ACTIVE,
            stability=3.0,
            evidence_count=10,
            user_forgotten=True,
        )
        await store.upsert(facet)
        await strategy.full_rebuild()
        updated = await store.find_by_key_value("bad", "disliked")
        assert updated is not None
        assert updated.lifecycle == PreferenceLifecycle.DROPPED
        assert updated.stability == 0.0
        await store.close()

    @pytest.mark.asyncio
    async def test_pinned_stays_active(self, store_path: str) -> None:
        store = SQLitePreferenceFacetStore(store_path)
        strategy = PreferenceStabilityStrategy(store)
        facet = PreferenceFacet(
            id="pin1",
            key="pinned",
            value="always",
            lifecycle=PreferenceLifecycle.ACTIVE,
            stability=float("inf"),
            user_pinned=True,
            last_seen=datetime.now(UTC) - timedelta(days=365),
        )
        await store.upsert(facet)
        await strategy.full_rebuild()
        updated = await store.find_by_key_value("pinned", "always")
        assert updated is not None
        assert updated.lifecycle == PreferenceLifecycle.ACTIVE
        await store.close()

    @pytest.mark.asyncio
    async def test_unpin_resumes_natural_decay(self, store_path: str) -> None:
        """Unpinning should recalculate stability and may demote from Active."""
        store = SQLitePreferenceFacetStore(store_path)
        facet = PreferenceFacet(
            id="unpin1",
            key="temp",
            value="was pinned",
            lifecycle=PreferenceLifecycle.ACTIVE,
            stability=float("inf"),
            evidence_count=1,
            user_pinned=True,
            last_seen=datetime.now(UTC) - timedelta(days=60),
        )
        await store.upsert(facet)
        facet.user_pinned = False
        facet.stability = StabilityScorer.score(facet)
        facet.lifecycle = StabilityScorer.classify(facet.stability)
        await store.upsert(facet)
        updated = await store.find_by_id("unpin1")
        assert updated is not None
        assert not updated.user_pinned
        assert updated.stability < float("inf")
        assert updated.stability != 0.0
        await store.close()

    @pytest.mark.asyncio
    async def test_unforget_restores_lifecycle(self, store_path: str) -> None:
        """Unforgetting should recalculate stability and restore from Dropped."""
        store = SQLitePreferenceFacetStore(store_path)
        facet = PreferenceFacet(
            id="unfg1",
            key="restored",
            value="was forgotten",
            lifecycle=PreferenceLifecycle.DROPPED,
            stability=0.0,
            evidence_count=3,
            user_forgotten=True,
            last_seen=datetime.now(UTC) - timedelta(days=2),
        )
        await store.upsert(facet)
        facet.user_forgotten = False
        facet.stability = StabilityScorer.score(facet)
        facet.lifecycle = StabilityScorer.classify(facet.stability)
        await store.upsert(facet)
        updated = await store.find_by_id("unfg1")
        assert updated is not None
        assert not updated.user_forgotten
        assert updated.stability > 0
        assert updated.lifecycle != PreferenceLifecycle.DROPPED
        await store.close()

    @pytest.mark.asyncio
    async def test_find_by_id(self, store_path: str) -> None:
        """find_by_id should return correct facet or None."""
        store = SQLitePreferenceFacetStore(store_path)
        facet = PreferenceFacet(id="fbi1", key="k", value="v")
        await store.upsert(facet)
        found = await store.find_by_id("fbi1")
        assert found is not None
        assert found.key == "k"
        missing = await store.find_by_id("nonexistent")
        assert missing is None
        await store.close()


# ── Category Inference Tests ─────────────────────────────────────────


class TestInferPreferenceCategory:
    def test_veto_before_tooling(self) -> None:
        """'don't use tabs' should match VETO, not TOOLING."""
        from myrm_agent_harness.toolkits.memory._manager.helpers import (
            _infer_preference_category,
        )
        from myrm_agent_harness.toolkits.memory.types import SemanticMemory

        mem = SemanticMemory(content="don't use tabs, use spaces")
        assert _infer_preference_category(mem) == PreferenceCategory.VETO

    def test_identity(self) -> None:
        from myrm_agent_harness.toolkits.memory._manager.helpers import (
            _infer_preference_category,
        )
        from myrm_agent_harness.toolkits.memory.types import SemanticMemory

        mem = SemanticMemory(content="I am a backend developer")
        assert _infer_preference_category(mem) == PreferenceCategory.IDENTITY

    def test_tooling(self) -> None:
        from myrm_agent_harness.toolkits.memory._manager.helpers import (
            _infer_preference_category,
        )
        from myrm_agent_harness.toolkits.memory.types import SemanticMemory

        mem = SemanticMemory(content="I use VSCode for development")
        assert _infer_preference_category(mem) == PreferenceCategory.TOOLING

    def test_style_fallback(self) -> None:
        from myrm_agent_harness.toolkits.memory._manager.helpers import (
            _infer_preference_category,
        )
        from myrm_agent_harness.toolkits.memory.types import SemanticMemory

        mem = SemanticMemory(content="I like clean and elegant code")
        assert _infer_preference_category(mem) == PreferenceCategory.STYLE
