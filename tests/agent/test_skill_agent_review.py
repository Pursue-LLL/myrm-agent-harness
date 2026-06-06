"""Tests for SkillAgentReviewMixin (_skill_agent_review.py).

Validates the session-end review orchestration layer:
- _should_trigger_skill_review decision logic
- _trigger_background_skill_review task scheduling
- _cleanup_session orchestration
- _build_recurrence_summary extraction
- _maybe_archive_to_wiki threshold + scheduling
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent._skill_agent_review import SkillAgentReviewMixin
from myrm_agent_harness.agent.types import AgentRunStatistics


@dataclass
class _FakeConfig:
    chat_id: str = "test-chat-001"


class FakeSkillAgent(SkillAgentReviewMixin):
    """Minimal stub implementing the attributes SkillAgentReviewMixin requires."""

    def __init__(
        self,
        *,
        stats: AgentRunStatistics | None = None,
        wiki_compiler: Any = None,
        wiki_structure: Any = None,
        extraction_llm: Any = None,
        on_skill_review_ready: Any = None,
        user_id: str | None = "user-1",
        last_context: dict[str, object] | None = None,
        agent_instance: Any = None,
        llm: Any = None,
        config: Any = None,
        enable_memory_auto_extraction: bool = False,
        memory_manager: Any = None,
    ) -> None:
        self.last_run_stats = stats
        self._wiki_compiler = wiki_compiler
        self._wiki_structure = wiki_structure
        self._extraction_llm = extraction_llm
        self._on_skill_review_ready = on_skill_review_ready
        self._user_id = user_id
        self._last_context = last_context
        self._agent = agent_instance
        self.llm = llm or MagicMock()
        self.config = config or _FakeConfig()
        self._enable_memory_auto_extraction = enable_memory_auto_extraction
        self.memory_manager = memory_manager
        self._active_skill: str | None = "test-skill"


# ---------------------------------------------------------------------------
# _build_recurrence_summary
# ---------------------------------------------------------------------------


class TestBuildRecurrenceSummary:
    def test_string_query(self) -> None:
        result = SkillAgentReviewMixin._build_recurrence_summary(
            "How to debug Python?", []
        )
        assert result == "How to debug Python?"

    def test_list_query_extracts_user_role(self) -> None:
        query = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Fix bug"},
        ]
        result = SkillAgentReviewMixin._build_recurrence_summary(query, [])
        assert "Hello" in result
        assert "Fix bug" in result
        assert "Hi" not in result

    def test_truncates_long_input(self) -> None:
        long_query = "x" * 500
        result = SkillAgentReviewMixin._build_recurrence_summary(long_query, [])
        assert len(result) == 300

    def test_non_string_non_list_returns_empty(self) -> None:
        assert SkillAgentReviewMixin._build_recurrence_summary(42, []) == ""

    def test_empty_string_returns_empty(self) -> None:
        assert SkillAgentReviewMixin._build_recurrence_summary("   ", []) == ""


# ---------------------------------------------------------------------------
# _should_trigger_skill_review
# ---------------------------------------------------------------------------


class TestShouldTriggerSkillReview:
    def test_no_stats_returns_false(self) -> None:
        agent = FakeSkillAgent(stats=None)
        assert agent._should_trigger_skill_review("hello") is False

    def test_deep_interaction_triggers(self) -> None:
        stats = AgentRunStatistics(tool_call_count=3)
        agent = FakeSkillAgent(stats=stats)
        assert agent._should_trigger_skill_review("x" * 60) is True

    def test_short_command_high_complexity_triggers(self) -> None:
        stats = AgentRunStatistics(tool_call_count=5)
        agent = FakeSkillAgent(stats=stats)
        assert agent._should_trigger_skill_review("hi") is True

    def test_low_stats_does_not_trigger(self) -> None:
        stats = AgentRunStatistics(tool_call_count=1)
        agent = FakeSkillAgent(stats=stats)
        assert agent._should_trigger_skill_review("hey") is False

    def test_too_complex_suppressed(self) -> None:
        stats = AgentRunStatistics(tool_call_count=60)
        agent = FakeSkillAgent(stats=stats)
        assert agent._should_trigger_skill_review("x" * 100) is False

    def test_multimodal_query(self) -> None:
        stats = AgentRunStatistics(tool_call_count=3)
        agent = FakeSkillAgent(stats=stats)
        query = [{"type": "text", "text": "a" * 60}]
        assert agent._should_trigger_skill_review(query) is True

    def test_resume_query(self) -> None:
        stats = AgentRunStatistics(tool_call_count=3)
        agent = FakeSkillAgent(stats=stats)

        class _ResumeQuery:
            resume = "x" * 60

        assert agent._should_trigger_skill_review(_ResumeQuery()) is True


# ---------------------------------------------------------------------------
# _trigger_background_skill_review
# ---------------------------------------------------------------------------


class TestTriggerBackgroundSkillReview:
    @pytest.mark.asyncio
    async def test_skips_when_too_few_messages(self) -> None:
        agent = FakeSkillAgent()
        await agent._trigger_background_skill_review("hi", None, [])

    @pytest.mark.asyncio
    async def test_schedules_task_with_chat_history(self) -> None:
        mock_llm = MagicMock()
        structured = MagicMock()
        mock_rubric = MagicMock()
        mock_rubric.total_score = 0.3
        mock_rubric.result_type = "nothing"
        structured.ainvoke = AsyncMock(return_value=mock_rubric)
        mock_llm.with_structured_output.return_value = structured

        agent = FakeSkillAgent(llm=mock_llm, extraction_llm=mock_llm)
        history = [
            HumanMessage(content="Fix the bug"),
            AIMessage(content="I'll look into it"),
        ]
        await agent._trigger_background_skill_review(
            "Fix the bug", history, ["I fixed the bug"]
        )
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_callback_invoked_on_success(self) -> None:
        mock_llm = MagicMock()
        structured = MagicMock()
        mock_rubric = MagicMock()
        mock_rubric.total_score = 0.9
        mock_rubric.anti_fragmentation_score = 0.9
        mock_rubric.sandbox_compatibility_score = 0.9
        mock_rubric.anti_pattern_score = 0.9
        mock_rubric.result_type = "semantic_memory"
        mock_rubric.skill_name = None
        mock_rubric.skill_description = None
        mock_rubric.trigger_condition = None
        mock_rubric.skill_steps = None
        mock_rubric.patch_content = None
        mock_rubric.content = "User prefers Python"
        structured.ainvoke = AsyncMock(return_value=mock_rubric)
        mock_llm.with_structured_output.return_value = structured

        callback = MagicMock()
        agent = FakeSkillAgent(
            llm=mock_llm,
            extraction_llm=mock_llm,
            on_skill_review_ready=callback,
        )
        history = [
            HumanMessage(content="I prefer Python"),
            AIMessage(content="Noted, I'll remember that"),
        ]
        await agent._trigger_background_skill_review(
            "I prefer Python", history, ["Noted"]
        )
        await asyncio.sleep(0.3)
        callback.assert_called_once()
        call_data = callback.call_args[0][0]
        assert call_data["has_value"] is True
        assert call_data["type"] == "semantic_memory"


# ---------------------------------------------------------------------------
# _maybe_archive_to_wiki
# ---------------------------------------------------------------------------


class TestMaybeArchiveToWiki:
    def test_skips_when_no_wiki(self) -> None:
        agent = FakeSkillAgent(wiki_compiler=None, wiki_structure=None)
        agent._maybe_archive_to_wiki("query", ["short"])

    def test_skips_short_reply(self) -> None:
        agent = FakeSkillAgent(
            wiki_compiler=MagicMock(), wiki_structure=MagicMock()
        )
        agent._maybe_archive_to_wiki("query", ["tiny"])

    @pytest.mark.asyncio
    async def test_schedules_archive_for_long_reply(self) -> None:
        mock_compiler = MagicMock()
        mock_compiler.compile_all = AsyncMock()
        mock_structure = MagicMock()
        mock_path = MagicMock()
        mock_structure.get_raw_file_path.return_value = mock_path

        agent = FakeSkillAgent(
            wiki_compiler=mock_compiler, wiki_structure=mock_structure
        )
        long_reply = ["x" * 600]
        agent._maybe_archive_to_wiki("query", long_reply)
        await asyncio.sleep(0.2)
        mock_path.write_text.assert_called_once()
        mock_compiler.compile_all.assert_called_once()


# ---------------------------------------------------------------------------
# _cleanup_session orchestration
# ---------------------------------------------------------------------------


class TestCleanupSession:
    @pytest.mark.asyncio
    async def test_resets_active_skill(self) -> None:
        agent = FakeSkillAgent()
        assert agent._active_skill == "test-skill"
        await agent._cleanup_session("hello", None, ["reply"])
        assert agent._active_skill is None

    @pytest.mark.asyncio
    async def test_calls_memory_end_session(self) -> None:
        mm = MagicMock()
        mm.active_session = MagicMock(chat_id="c1")
        mm.end_session = AsyncMock(return_value=["mem1"])
        mm.check_session_recurrence = AsyncMock()
        agent = FakeSkillAgent(memory_manager=mm)
        await agent._cleanup_session("hello", None, ["reply"])
        await asyncio.sleep(0.1)
        mm.end_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_triggers_recurrence_check(self) -> None:
        mm = MagicMock()
        mm.active_session = MagicMock(chat_id="c1")
        mm.end_session = AsyncMock(return_value=[])
        mm.check_session_recurrence = AsyncMock()
        agent = FakeSkillAgent(memory_manager=mm)
        await agent._cleanup_session("How to debug?", None, ["Use print"])
        await asyncio.sleep(0.1)
        mm.check_session_recurrence.assert_called_once()

    @pytest.mark.asyncio
    async def test_skill_review_triggered_when_stats_sufficient(self) -> None:
        stats = AgentRunStatistics(tool_call_count=5)
        agent = FakeSkillAgent(stats=stats)
        with patch.object(
            agent, "_trigger_background_skill_review", new_callable=AsyncMock
        ) as mock_trigger:
            await agent._cleanup_session("x" * 60, None, ["reply"])
            mock_trigger.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_review_when_stats_insufficient(self) -> None:
        stats = AgentRunStatistics(tool_call_count=1)
        agent = FakeSkillAgent(stats=stats)
        with patch.object(
            agent, "_trigger_background_skill_review", new_callable=AsyncMock
        ) as mock_trigger:
            await agent._cleanup_session("hi", None, ["ok"])
            mock_trigger.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_cleanup_hook_called(self) -> None:
        hook = AsyncMock()
        agent = FakeSkillAgent()
        agent._on_session_cleanup = hook
        await agent._cleanup_session("test", None, ["reply"])
        await asyncio.sleep(0.1)
        hook.assert_called_once()
        messages = hook.call_args[0][0]
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == "reply"
