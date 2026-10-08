"""Branch coverage for SkillAgentReviewMixin session-end paths.

Complements test_skill_agent_review.py with the pre-screener, state-fetch, reviewer
failure isolation, wiki archive outcomes and session-cleanup hooks.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent.skill_agent.review import SkillAgentReviewMixin
from myrm_agent_harness.agent.types import AgentRunStatistics

_REVIEWER = "myrm_agent_harness.agent.skills.evolution.review.reviewer.review_trajectory_with_llm"
_PRUNER = "myrm_agent_harness.agent.skills.evolution.review.pruner.prune_trajectory"
_EXECUTOR = "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor"
_PUBLISH_RAW = "myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.publish_raw"

_HISTORY = [HumanMessage(content="earlier question"), AIMessage(content="earlier answer")]


class _Host(SkillAgentReviewMixin):
    """Minimal host exposing only what the mixin reads."""

    def __init__(self, **attrs: object) -> None:
        self.llm = MagicMock()
        self.last_run_stats: AgentRunStatistics | None = None
        self._active_skill = None
        for name, value in attrs.items():
            setattr(self, name, value)


async def _drain_background_tasks() -> None:
    """Await every task the code under test scheduled, so assertions are deterministic."""
    pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    await asyncio.gather(*pending)


def _review_result(*, has_value: bool = True) -> MagicMock:
    result = MagicMock()
    result.has_value = has_value
    result.result_type = "semantic_memory"
    result.content = "User prefers Python"
    result.to_dict.return_value = {"has_value": has_value}
    return result


class TestPreScreener:
    def test_cancelled_run_is_skipped(self) -> None:
        host = _Host(last_run_stats=AgentRunStatistics(tool_call_count=9, was_cancelled=True))
        assert host._should_trigger_skill_review("x" * 80) is False

    def test_fatal_error_run_is_skipped(self) -> None:
        host = _Host(last_run_stats=AgentRunStatistics(tool_call_count=9, error_message="boom"))
        assert host._should_trigger_skill_review("x" * 80) is False

    def test_run_without_a_successful_tool_execution_is_skipped(self) -> None:
        executor = MagicMock()
        executor.metrics.total_executions = 3
        executor.metrics.total_success = 0
        host = _Host(last_run_stats=AgentRunStatistics(tool_call_count=5))
        with patch(_EXECUTOR, return_value=executor):
            assert host._should_trigger_skill_review("x" * 80) is False

    def test_executor_lookup_failure_does_not_block_review(self) -> None:
        host = _Host(last_run_stats=AgentRunStatistics(tool_call_count=5))
        with patch(_EXECUTOR, side_effect=RuntimeError("no executor")):
            assert host._should_trigger_skill_review("x" * 80) is True


class TestReviewTaskInputs:
    @pytest.mark.asyncio
    async def test_full_graph_state_replaces_the_supplied_history(self) -> None:
        state_messages = [HumanMessage(content="a"), AIMessage(content="b"), HumanMessage(content="c")]
        graph = MagicMock()
        graph.aget_state = AsyncMock(return_value=MagicMock(values={"messages": state_messages}))
        host = _Host(_agent=graph, _extraction_llm=MagicMock())

        with (
            patch(_PRUNER, return_value="skeleton") as prune,
            patch(_REVIEWER, new_callable=AsyncMock, return_value=None),
        ):
            await host._trigger_background_skill_review("query", _HISTORY, ["reply"])
            await _drain_background_tasks()

        assert prune.call_args.args[0] == state_messages

    @pytest.mark.asyncio
    async def test_state_fetch_failure_falls_back_to_history_plus_turn(self) -> None:
        graph = MagicMock()
        graph.aget_state = AsyncMock(side_effect=RuntimeError("checkpoint unavailable"))
        host = _Host(_agent=graph)

        with (
            patch(_PRUNER, return_value="skeleton") as prune,
            patch(_REVIEWER, new_callable=AsyncMock, return_value=None),
        ):
            await host._trigger_background_skill_review("query", _HISTORY, ["reply"])
            await _drain_background_tasks()

        rebuilt = prune.call_args.args[0]
        assert [message.content for message in rebuilt] == [
            "earlier question",
            "earlier answer",
            "query",
            "reply",
        ]

    @pytest.mark.asyncio
    async def test_skill_catalog_is_passed_to_the_reviewer(self) -> None:
        skill = MagicMock()
        skill.name = "debugging"
        skill.description = "Find root causes"
        host = _Host(_get_cached_skills=AsyncMock(return_value=[skill]))

        with patch(_REVIEWER, new_callable=AsyncMock, return_value=None) as reviewer:
            await host._trigger_background_skill_review("query", _HISTORY, ["reply"])
            await _drain_background_tasks()

        assert reviewer.await_args.kwargs["all_skills_catalog"] == "- debugging — Find root causes"

    @pytest.mark.asyncio
    async def test_skill_catalog_failure_does_not_block_review(self) -> None:
        host = _Host(_get_cached_skills=AsyncMock(side_effect=RuntimeError("backend down")))

        with patch(_REVIEWER, new_callable=AsyncMock, return_value=None) as reviewer:
            await host._trigger_background_skill_review("query", _HISTORY, ["reply"])
            await _drain_background_tasks()

        assert reviewer.await_args.kwargs["all_skills_catalog"] is None


class TestReviewTaskOutcomes:
    @pytest.mark.asyncio
    async def test_empty_skeleton_never_reaches_the_reviewer(self) -> None:
        host = _Host()

        with (
            patch(_PRUNER, return_value=""),
            patch(_REVIEWER, new_callable=AsyncMock) as reviewer,
        ):
            await host._trigger_background_skill_review("query", _HISTORY, ["reply"])
            await _drain_background_tasks()

        reviewer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_result_is_stamped_with_the_session_identity(self) -> None:
        result = _review_result()
        callback = MagicMock()
        host = _Host(
            _on_skill_review_ready=callback,
            _last_context={"user_id": "u1", "agent_id": "a1", "chat_id": "c1"},
        )

        with patch(_REVIEWER, new_callable=AsyncMock, return_value=result):
            await host._trigger_background_skill_review("query", _HISTORY, ["reply"])
            await _drain_background_tasks()

        assert (result.user_id, result.agent_id, result.chat_id) == ("u1", "a1", "c1")
        callback.assert_called_once_with({"has_value": True})

    @pytest.mark.asyncio
    async def test_callback_failure_is_contained(self) -> None:
        callback = MagicMock(side_effect=RuntimeError("ui gone"))
        host = _Host(_on_skill_review_ready=callback)

        with patch(_REVIEWER, new_callable=AsyncMock, return_value=_review_result()):
            await host._trigger_background_skill_review("query", _HISTORY, ["reply"])
            await _drain_background_tasks()

        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_reviewer_failure_is_contained(self) -> None:
        callback = MagicMock()
        host = _Host(_on_skill_review_ready=callback)

        with patch(_REVIEWER, new_callable=AsyncMock, side_effect=ValueError("bad rubric")):
            await host._trigger_background_skill_review("query", _HISTORY, ["reply"])
            await _drain_background_tasks()

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_loop_shutdown_race_is_not_an_error(self) -> None:
        callback = MagicMock()
        host = _Host(_on_skill_review_ready=callback)

        with patch(_REVIEWER, new_callable=AsyncMock, side_effect=RuntimeError("no running event loop")):
            await host._trigger_background_skill_review("query", _HISTORY, ["reply"])
            await _drain_background_tasks()

        callback.assert_not_called()


class TestWikiArchiveOutcomes:
    def _host(self) -> tuple[_Host, MagicMock]:
        compiler = MagicMock()
        return _Host(_wiki_compiler=compiler, _wiki_structure=MagicMock(), config=MagicMock(chat_id=None)), compiler

    @pytest.mark.asyncio
    async def test_security_blocked_archive_is_not_enqueued(self) -> None:
        host, compiler = self._host()

        with patch(_PUBLISH_RAW, new_callable=AsyncMock, return_value=MagicMock(security_blocked=True)):
            host._maybe_archive_to_wiki("query", ["x" * 600], chat_id="c1")
            await _drain_background_tasks()

        compiler.enqueue_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_unwritten_archive_is_not_enqueued(self) -> None:
        host, compiler = self._host()
        outcome = MagicMock(security_blocked=False, written=False)

        with patch(_PUBLISH_RAW, new_callable=AsyncMock, return_value=outcome):
            host._maybe_archive_to_wiki("query", ["x" * 600], chat_id="c1")
            await _drain_background_tasks()

        compiler.enqueue_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_failure_is_contained(self) -> None:
        host, compiler = self._host()

        with patch(_PUBLISH_RAW, new_callable=AsyncMock, side_effect=OSError("disk full")):
            host._maybe_archive_to_wiki("query", ["x" * 600], chat_id="c1")
            await _drain_background_tasks()

        compiler.enqueue_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_chat_id_falls_back_to_runtime_config(self) -> None:
        compiler = MagicMock()
        host = _Host(_wiki_compiler=compiler, _wiki_structure=MagicMock(), config=MagicMock(chat_id="from-config"))
        outcome = MagicMock(security_blocked=False, written=True, absolute_path="/tmp/turn.md")

        with patch(_PUBLISH_RAW, new_callable=AsyncMock, return_value=outcome) as publish:
            host._maybe_archive_to_wiki("query", ["x" * 600])
            await _drain_background_tasks()

        assert publish.await_args.args[1].relative_path.startswith("turn_from-config_")
        compiler.enqueue_file.assert_called_once_with("/tmp/turn.md")


class TestSessionCleanupHooks:
    @pytest.mark.asyncio
    async def test_hook_receives_message_list_queries(self) -> None:
        hook = AsyncMock()
        host = _Host(_on_session_cleanup=hook)
        query = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "second"}]

        await host._cleanup_session(query, None, ["reply"], run_chat_id="c1")
        await _drain_background_tasks()

        messages, chat_id = hook.await_args.args
        assert [(m["role"], m["content"]) for m in messages] == [
            ("user", "first"),
            ("assistant", "second"),
            ("assistant", "reply"),
        ]
        assert chat_id == "c1"

    @pytest.mark.asyncio
    async def test_hook_receives_only_the_reply_for_a_hitl_resume(self) -> None:
        hook = AsyncMock()
        host = _Host(_on_session_cleanup=hook)

        await host._cleanup_session(Command(resume="approved"), None, ["reply"], run_chat_id="c1")
        await _drain_background_tasks()

        assert hook.await_args.args[0] == [{"role": "assistant", "content": "reply"}]

    @pytest.mark.asyncio
    async def test_hook_failure_is_contained(self) -> None:
        hook = AsyncMock(side_effect=RuntimeError("hook failed"))
        host = _Host(_on_session_cleanup=hook)

        await host._cleanup_session("query", None, ["reply"], run_chat_id="c1")
        await _drain_background_tasks()

        hook.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_loaded_skills_are_persisted_for_the_chat(self) -> None:
        persist = AsyncMock()
        host = _Host(_on_loaded_skills_persist=persist)

        await host._cleanup_session("query", None, ["reply"], active_skills=["debugging"], run_chat_id="c1")
        await _drain_background_tasks()

        persist.assert_awaited_once_with(["debugging"], "c1")

    @pytest.mark.asyncio
    async def test_loaded_skills_persist_failure_is_contained(self) -> None:
        persist = AsyncMock(side_effect=RuntimeError("store down"))
        host = _Host(_on_loaded_skills_persist=persist)

        await host._cleanup_session("query", None, ["reply"], run_chat_id="c1")
        await _drain_background_tasks()

        persist.assert_awaited_once_with([], "c1")
