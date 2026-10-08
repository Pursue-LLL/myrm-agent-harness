"""Session lifecycle side effects: hook wiring, preference promotion, forgetting and consolidation scheduling."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.hooks.types import HookEvent
from myrm_agent_harness.toolkits.memory.config import ConsolidationConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.strategies.preference_stability import CueFamily, PreferenceFacet
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory, SemanticMemory

_SESSION = "myrm_agent_harness.toolkits.memory._manager.governance_session"


class _Registry:
    """Smallest object satisfying the hook registry contract."""

    def __init__(self) -> None:
        self._hooks: dict[str, list] = {}

    def register(self, event, hook) -> None:
        self._hooks.setdefault(event, []).append(hook)


def _build(memory_config, mock_vector_store, mock_relational_store, mock_embedding, **overrides) -> MemoryManager:
    return MemoryManager(
        memory_config,
        user_id="test_user",
        vector=mock_vector_store,
        relational=mock_relational_store,
        embedding=mock_embedding,
        approval_required=False,
        **overrides,
    )


@pytest.fixture
def manager(memory_config, mock_vector_store, mock_relational_store, mock_embedding) -> MemoryManager:
    return _build(memory_config, mock_vector_store, mock_relational_store, mock_embedding)


class TestBeginSession:
    def test_tool_capture_hooks_are_registered_once_per_registry(self, manager):
        registry = _Registry()

        manager.begin_session("chat-1", hook_registry=registry)
        manager.begin_session("chat-2", hook_registry=registry)

        for event in (HookEvent.POST_TOOL_USE_FAILURE, HookEvent.POST_TOOL_USE, HookEvent.USER_TURN):
            assert len(registry._hooks[event]) == 1


class TestEndSession:
    @pytest.mark.asyncio
    async def test_newly_active_core_preferences_are_promoted_to_the_profile(self, manager):
        strategy = AsyncMock()
        strategy.get_active_preferences.return_value = []
        strategy.micro_rebuild.return_value = 2
        manager._preference_strategy = strategy
        manager._promote_core_preferences_to_profile = AsyncMock()
        manager.begin_session("chat-1")

        await manager.end_session()

        manager._promote_core_preferences_to_profile.assert_awaited_once_with(set())

    @pytest.mark.asyncio
    async def test_a_failing_preference_rebuild_never_breaks_the_session_end(self, manager):
        strategy = AsyncMock()
        strategy.get_active_preferences.return_value = []
        strategy.micro_rebuild.side_effect = RuntimeError("store unavailable")
        manager._preference_strategy = strategy
        manager.begin_session("chat-1")

        assert await manager.end_session() == []

    @pytest.mark.asyncio
    async def test_forgetting_is_scheduled_on_the_configured_session_interval(
        self, memory_config, mock_vector_store, mock_relational_store, mock_embedding
    ):
        manager = _build(
            replace(memory_config, forgetting_interval=2), mock_vector_store, mock_relational_store, mock_embedding
        )
        manager._guarded_forgetting = AsyncMock()

        for chat in ("chat-1", "chat-2", "chat-3"):
            manager.begin_session(chat)
            await manager.end_session()
        await asyncio.sleep(0)

        manager._guarded_forgetting.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ending_without_an_active_session_is_a_noop(self, manager):
        assert await manager.end_session() == []


class TestGuardedForgetting:
    @pytest.mark.asyncio
    async def test_forgetting_runs_under_the_maintenance_lock(self, manager):
        with patch(f"{_SESSION}.run_forgetting", new=AsyncMock()) as run:
            await manager._guarded_forgetting()

        run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_forgetting_is_skipped_while_another_maintenance_job_holds_the_lock(self, manager):
        with patch(f"{_SESSION}.run_forgetting", new=AsyncMock()) as run:
            async with manager._maintenance_lock:
                await manager._guarded_forgetting()

        run.assert_not_called()

    @pytest.mark.asyncio
    async def test_forgetting_needs_a_vector_backend(self, manager):
        manager._vector = None

        with patch(f"{_SESSION}.run_forgetting", new=AsyncMock()) as run:
            await manager._guarded_forgetting()

        run.assert_not_called()


class TestRecurrence:
    @pytest.mark.asyncio
    async def test_recurrence_check_is_skipped_without_a_detector(self, manager):
        manager._recurrence_detector = None

        await manager._check_recurrence_and_store("topic summary")

        assert manager._recurrence_detector is None


class TestCoreProfilePromotion:
    @staticmethod
    def _facet(key: str, value: str) -> PreferenceFacet:
        return PreferenceFacet(key=key, value=value)

    @pytest.mark.asyncio
    async def test_only_new_core_keys_reach_the_profile(self, manager):
        strategy = AsyncMock()
        strategy.get_active_preferences.return_value = [
            self._facet("reply_style", "concise"),
            self._facet("proactivity", "high"),
            self._facet("favorite_color", "blue"),
        ]
        manager._preference_strategy = strategy
        manager.set_system_profile_attribute = AsyncMock()

        await manager._promote_core_preferences_to_profile({"proactivity"})

        manager.set_system_profile_attribute.assert_awaited_once_with("reply_style", "concise")

    @pytest.mark.asyncio
    async def test_a_failing_profile_write_is_contained(self, manager):
        strategy = AsyncMock()
        strategy.get_active_preferences.return_value = [self._facet("reply_style", "concise")]
        manager._preference_strategy = strategy
        manager.set_system_profile_attribute = AsyncMock(side_effect=RuntimeError("profile locked"))

        await manager._promote_core_preferences_to_profile(set())

        manager.set_system_profile_attribute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_promotion_needs_a_preference_strategy(self, manager):
        manager._preference_strategy = None
        manager.set_system_profile_attribute = AsyncMock()

        await manager._promote_core_preferences_to_profile(set())

        manager.set_system_profile_attribute.assert_not_called()


class TestPreferenceCandidates:
    @pytest.mark.asyncio
    async def test_explicit_preference_is_submitted_with_its_cue_and_strength(self, manager):
        strategy = AsyncMock()
        manager._preference_strategy = strategy
        memory = SemanticMemory(
            id="mem-1", content="I always want concise replies", preference_type="explicit", preference_strength=0.9
        )

        await manager._submit_preference_candidate(memory)

        candidate = strategy.submit_candidate.await_args.args[0]
        assert candidate.cue == CueFamily.EXPLICIT
        assert candidate.strength == 0.9
        assert candidate.memory_id == "mem-1"

    @pytest.mark.asyncio
    async def test_implicit_preference_without_strength_gets_the_default_strength(self, manager):
        strategy = AsyncMock()
        manager._preference_strategy = strategy
        memory = SemanticMemory(id="mem-2", content="Prefers tea", preference_type="implicit")

        await manager._submit_preference_candidate(memory)

        candidate = strategy.submit_candidate.await_args.args[0]
        assert candidate.cue == CueFamily.IMPLICIT
        assert candidate.strength == 0.5

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "memory",
        [
            SemanticMemory(id="mem-3", content="No preference label"),
            ProceduralMemory(id="rule-1", trigger="when asked", action="answer briefly"),
        ],
        ids=["no-preference-type", "not-semantic"],
    )
    async def test_memories_that_are_not_preferences_are_ignored(self, manager, memory):
        strategy = AsyncMock()
        manager._preference_strategy = strategy

        await manager._submit_preference_candidate(memory)

        strategy.submit_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_submission_needs_a_preference_strategy(self, manager):
        manager._preference_strategy = None

        await manager._submit_preference_candidate(SemanticMemory(id="mem-4", content="x", preference_type="explicit"))

    @pytest.mark.asyncio
    async def test_a_failing_submission_is_contained(self, manager):
        strategy = AsyncMock()
        strategy.submit_candidate.side_effect = RuntimeError("store unavailable")
        manager._preference_strategy = strategy

        await manager._submit_preference_candidate(
            SemanticMemory(id="mem-5", content="Prefers tea", preference_type="implicit")
        )

        strategy.submit_candidate.assert_awaited_once()


class TestConsolidationScheduling:
    @staticmethod
    def _enabled(memory_config):
        return replace(memory_config, consolidation=ConsolidationConfig(enabled=True))

    @pytest.mark.asyncio
    async def test_consolidation_is_scheduled_when_enabled_and_backed_by_an_llm(
        self, memory_config, mock_vector_store, mock_relational_store, mock_embedding
    ):
        manager = _build(
            self._enabled(memory_config),
            mock_vector_store,
            mock_relational_store,
            mock_embedding,
            consolidation_llm=MagicMock(),
        )
        manager._run_consolidation_safe = AsyncMock()

        manager._maybe_consolidate()
        await asyncio.sleep(0)

        manager._run_consolidation_safe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_consolidation_is_skipped_without_an_llm(
        self, memory_config, mock_vector_store, mock_relational_store, mock_embedding
    ):
        manager = _build(self._enabled(memory_config), mock_vector_store, mock_relational_store, mock_embedding)
        manager._run_consolidation_safe = AsyncMock()

        manager._maybe_consolidate()
        await asyncio.sleep(0)

        manager._run_consolidation_safe.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidation_is_skipped_when_disabled(
        self, memory_config, mock_vector_store, mock_relational_store, mock_embedding
    ):
        manager = _build(
            replace(memory_config, consolidation=ConsolidationConfig(enabled=False)),
            mock_vector_store,
            mock_relational_store,
            mock_embedding,
            consolidation_llm=MagicMock(),
        )
        manager._run_consolidation_safe = AsyncMock()

        manager._maybe_consolidate()
        await asyncio.sleep(0)

        manager._run_consolidation_safe.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidation_needs_both_stores(self, memory_config, mock_vector_store, mock_embedding):
        manager = MemoryManager(
            self._enabled(memory_config),
            user_id="test_user",
            vector=mock_vector_store,
            embedding=mock_embedding,
            approval_required=False,
            consolidation_llm=MagicMock(),
        )
        manager._run_consolidation_safe = AsyncMock()

        manager._maybe_consolidate()
        await asyncio.sleep(0)

        manager._run_consolidation_safe.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_running_maintenance_job_defers_consolidation(self, manager, memory_config):
        manager._run_consolidation_safe = AsyncMock()

        async with manager._maintenance_lock:
            await manager._guarded_consolidation(memory_config.consolidation)

        manager._run_consolidation_safe.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidation_runs_under_the_maintenance_lock(self, manager, memory_config):
        manager._run_consolidation_safe = AsyncMock()

        await manager._guarded_consolidation(memory_config.consolidation)

        manager._run_consolidation_safe.assert_awaited_once_with(memory_config.consolidation)
