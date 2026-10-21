"""Success-path and error-swallow branch tests for pattern discovery.

Complements the gate/schema tests by exercising the full successful cycle —
persistence of discovered patterns as episodic events, ProceduralRule
promotion, discovery timestamp + memory-hash bookkeeping — plus every
non-fatal error branch that must degrade to a warning log instead of raising.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.strategies.pattern_discovery import (
    _PROFILE_KEY_LAST_PATTERN_DISCOVERY,
    _PROFILE_KEY_MEMORY_SET_HASH,
    _build_discovery_prompt,
    _collect_claims,
    _collect_insights,
    _persist_patterns,
    _promote_patterns_to_rules,
    _update_discovery_timestamp,
    get_recent_patterns,
    run_pattern_discovery,
)
from myrm_agent_harness.toolkits.memory.types import (
    ProceduralMemory,
    SemanticMemory,
)


def _mature_manager(**overrides: object) -> AsyncMock:
    """Manager stub that passes the maturity gate by default."""
    manager = AsyncMock()
    manager.has_relational = True
    manager.has_vector = True
    manager.has_graph = False
    manager.count_memories = AsyncMock(side_effect=lambda mt: 60)
    manager.get_profile_attribute = AsyncMock(side_effect=lambda key: "5")
    manager.set_profile_attribute = AsyncMock()
    manager.search = AsyncMock(return_value=[])
    manager.add_event = AsyncMock()
    manager.store = AsyncMock(return_value=SimpleNamespace(id="stored-rule"))
    manager.list_memories = AsyncMock(return_value=[])
    for key, value in overrides.items():
        setattr(manager, key, value)
    return manager


def _memories(count: int) -> list[SemanticMemory]:
    return [
        SemanticMemory(content=f"reference note {i}: design rationale", tags=["reference"])
        for i in range(count)
    ]


def _pattern(*, title: str, confidence: float, durability: str = "emerging") -> object:
    from myrm_agent_harness.toolkits.memory.strategies.pattern_discovery import (
        DiscoveredPattern,
        PatternDurability,
    )

    return DiscoveredPattern(
        title=title,
        description="desc",
        evidence_summary="evidence",
        confidence=confidence,
        actionable_suggestion="suggestion",
        durability=PatternDurability(durability),
    )


def _structured_llm(response: object, *, raises: BaseException | None = None) -> MagicMock:
    llm = MagicMock()
    structured = AsyncMock()
    structured.ainvoke = AsyncMock(return_value=response) if raises is None else AsyncMock(side_effect=raises)
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


class TestCollectInsights:
    @pytest.mark.asyncio
    async def test_search_failure_degrades_to_empty(self) -> None:
        manager = _mature_manager()
        manager.search = AsyncMock(side_effect=RuntimeError("search down"))
        assert await _collect_insights(manager) == []

    @pytest.mark.asyncio
    async def test_filters_tagged_insights(self) -> None:
        tagged = SimpleNamespace(memory=SimpleNamespace(content="insight A", tags=["consolidation-insight"]))
        untagged = SimpleNamespace(memory=SimpleNamespace(content="plain", tags=["other"]))
        manager = _mature_manager()
        manager.search = AsyncMock(return_value=[tagged, untagged])
        assert await _collect_insights(manager) == ["insight A"]


class TestCollectClaims:
    @pytest.mark.asyncio
    async def test_returns_empty_without_graph(self) -> None:
        manager = _mature_manager(has_graph=False)
        assert await _collect_claims(manager) == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_graph_none(self) -> None:
        manager = _mature_manager(has_graph=True)
        manager._graph = None
        assert await _collect_claims(manager) == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_scroll_fails(self) -> None:
        class _BrokenGraph:
            async def find_nodes(self, *_args: object, **_kwargs: object) -> object:
                raise RuntimeError("graph down")

        manager = _mature_manager(has_graph=True)
        manager._graph = _BrokenGraph()
        assert await _collect_claims(manager) == []

    @pytest.mark.asyncio
    async def test_returns_claim_contents(self) -> None:
        class _FakeGraph:
            async def find_nodes(self, *_args: object, **_kwargs: object) -> list[object]:
                return [
                    SimpleNamespace(properties={"content": "claim one"}),
                    SimpleNamespace(properties={"content": ""}),
                    SimpleNamespace(properties={}),
                ]

        manager = _mature_manager(has_graph=True)
        manager._graph = _FakeGraph()
        assert await _collect_claims(manager) == ["claim one"]


class TestBuildDiscoveryPrompt:
    def test_includes_insights_and_claims_sections(self) -> None:
        mem = SemanticMemory(content="a reference note", tags=["reference"])
        prompt = _build_discovery_prompt(
            memories=[mem],
            insights=["insight line"],
            claims=["claim line"],
            today="2026-08-16",
        )
        assert "Analysis date: 2026-08-16" in prompt
        assert "## Consolidation Insights" in prompt
        assert "insight line" in prompt
        assert "## Knowledge Claims" in prompt
        assert "claim line" in prompt

    def test_omits_empty_sections(self) -> None:
        prompt = _build_discovery_prompt(
            memories=[],
            insights=[],
            claims=[],
            today="2026-08-16",
        )
        assert "## Consolidation Insights" not in prompt
        assert "## Knowledge Claims" not in prompt


class TestRunPatternDiscoverySuccess:
    @pytest.mark.asyncio
    async def test_full_cycle_persists_and_bookkeeps(self) -> None:
        from myrm_agent_harness.toolkits.memory.strategies.pattern_discovery import (
            PatternDiscoveryResponse,
        )

        memories = _memories(5)
        manager = _mature_manager()
        manager.list_memories = AsyncMock(return_value=memories)
        manager.get_profile_attribute = AsyncMock(
            side_effect=lambda key: None if key == _PROFILE_KEY_MEMORY_SET_HASH else "5"
        )
        response = PatternDiscoveryResponse(
            patterns=[
                _pattern(title="habit", confidence=0.9, durability="established"),
                _pattern(title="emerging one", confidence=0.6),
            ],
            meta_observation="user is becoming more structured",
        )
        llm = _structured_llm(response)

        report = await run_pattern_discovery(manager, llm)

        assert report.skipped is False
        assert report.has_patterns is True
        assert report.memory_count == 10  # SEMANTIC + EPISODIC passes.
        assert report.insight_count == 0
        # Patterns persisted as an episodic event.
        manager.add_event.assert_awaited_once()
        # Established high-confidence pattern promoted to a ProceduralRule.
        store_args = manager.store.await_args.args[0]
        assert isinstance(store_args, ProceduralMemory)
        assert store_args.source.value == "agent_self"
        # Discovery timestamp + memory-set hash recorded.
        manager.set_profile_attribute.assert_any_await(
            _PROFILE_KEY_LAST_PATTERN_DISCOVERY, ANY
        )
        manager.set_profile_attribute.assert_any_await(
            _PROFILE_KEY_MEMORY_SET_HASH, ANY
        )


class TestPersistPatternsFailure:
    @pytest.mark.asyncio
    async def test_add_event_failure_swallowed(self) -> None:
        manager = _mature_manager()
        manager.add_event = AsyncMock(side_effect=RuntimeError("vector down"))
        # Emerging pattern is not promotable; the add_event failure must not raise.
        await _persist_patterns(manager, [_pattern(title="t", confidence=0.6)], "obs")
        manager.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_event_failure_still_promotes_qualifying(self) -> None:
        manager = _mature_manager()
        manager.add_event = AsyncMock(side_effect=RuntimeError("vector down"))
        await _persist_patterns(
            manager,
            [_pattern(title="t", confidence=0.9, durability="established")],
            "obs",
        )
        manager.store.assert_awaited_once()  # Promotion unaffected by event failure.

    @pytest.mark.asyncio
    async def test_store_failure_swallowed(self) -> None:
        manager = _mature_manager()
        manager.store = AsyncMock(side_effect=RuntimeError("relational down"))
        await _persist_patterns(manager, [_pattern(title="t", confidence=0.9, durability="established")], "")
        manager.add_event.assert_awaited_once()


class TestPromotePatternsToRules:
    @pytest.mark.asyncio
    async def test_returns_zero_without_relational(self) -> None:
        manager = _mature_manager(has_relational=False)
        promoted = await _promote_patterns_to_rules(
            manager, [_pattern(title="t", confidence=0.9, durability="established")]
        )
        assert promoted == 0
        manager.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_promotes_only_qualifying(self) -> None:
        manager = _mature_manager()
        promoted = await _promote_patterns_to_rules(
            manager,
            [
                _pattern(title="good", confidence=0.9, durability="established"),
                _pattern(title="weak", confidence=0.6),
            ],
        )
        assert promoted == 1
        stored = manager.store.await_args.args[0]
        assert stored.content == "good"


class TestUpdateDiscoveryTimestamp:
    @pytest.mark.asyncio
    async def test_skips_without_relational(self) -> None:
        manager = _mature_manager(has_relational=False)
        await _update_discovery_timestamp(manager, datetime.now(UTC))
        manager.set_profile_attribute.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_iso_timestamp(self) -> None:
        manager = _mature_manager()
        ts = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)
        await _update_discovery_timestamp(manager, ts)
        manager.set_profile_attribute.assert_awaited_once_with(
            _PROFILE_KEY_LAST_PATTERN_DISCOVERY, ts.isoformat()
        )

    @pytest.mark.asyncio
    async def test_failure_swallowed(self) -> None:
        manager = _mature_manager()
        manager.set_profile_attribute = AsyncMock(side_effect=RuntimeError("write down"))
        await _update_discovery_timestamp(manager, datetime.now(UTC))  # No raise.


class TestGetRecentPatternsFilter:
    @pytest.mark.asyncio
    async def test_filters_empty_contents(self) -> None:
        class _FakeVector:
            async def scroll(self, *_args: object, **_kwargs: object) -> tuple[list[object], object]:
                return [SimpleNamespace(content=""), SimpleNamespace(content="real")], None

        manager = _mature_manager()
        manager._vector = _FakeVector()
        assert await get_recent_patterns(manager) == ["real"]
