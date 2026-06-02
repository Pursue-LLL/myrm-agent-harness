"""Tests for Session Notes (schemas, trigger, updater, processor)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.session_notes.schemas import (
    DEFAULT_SECTIONS,
    MIN_READY_TOKENS,
    REQUIRED_SECTIONS_FOR_READY,
    NoteSection,
    SessionNotes,
    SessionNotesConfig,
)
from myrm_agent_harness.agent.context_management.strategies.session_notes.trigger import (
    SessionNotesTrigger,
    should_update_notes,
)

# ---------------------------------------------------------------------------
# schemas.py
# ---------------------------------------------------------------------------


class TestNoteSection:
    def test_defaults(self) -> None:
        s = NoteSection(key="k", title="T", description="D")
        assert s.content == ""
        assert s.max_tokens == 2000


class TestSessionNotesConfig:
    def test_defaults(self) -> None:
        cfg = SessionNotesConfig()
        assert cfg.init_token_threshold == 8000
        assert cfg.update_token_threshold == 5000
        assert cfg.update_tool_call_threshold == 3
        assert cfg.full_refresh_interval == 5
        assert cfg.max_consecutive_failures == 3
        assert cfg.wait_timeout_seconds == 10.0

    def test_custom(self) -> None:
        cfg = SessionNotesConfig(init_token_threshold=1000, update_token_threshold=500)
        assert cfg.init_token_threshold == 1000
        assert cfg.update_token_threshold == 500


class TestSessionNotes:
    def test_default_sections(self) -> None:
        notes = SessionNotes()
        assert len(notes.sections) == len(DEFAULT_SECTIONS)
        assert notes.sections[0].key == "session_title"

    def test_sections_are_deep_copied(self) -> None:
        notes1 = SessionNotes()
        notes2 = SessionNotes()
        notes1.sections[0].content = "changed"
        assert notes2.sections[0].content == ""

    def test_is_ready_false_when_empty(self) -> None:
        notes = SessionNotes()
        assert not notes.is_ready()

    def test_is_ready_false_when_missing_required(self) -> None:
        notes = SessionNotes()
        notes.get_section("current_state").content = "x" * (MIN_READY_TOKENS * 4)
        assert not notes.is_ready()

    def test_is_ready_true(self) -> None:
        notes = SessionNotes()
        content = "x" * (MIN_READY_TOKENS * 4)
        for key in REQUIRED_SECTIONS_FOR_READY:
            notes.get_section(key).content = content
        assert notes.is_ready()

    def test_estimate_total_tokens(self) -> None:
        notes = SessionNotes()
        notes.get_section("current_state").content = "a" * 400
        assert notes.estimate_total_tokens() == 100

    def test_to_summary_text(self) -> None:
        notes = SessionNotes()
        notes.get_section("session_title").content = "My Session"
        text = notes.to_summary_text()
        assert "## Session Title" in text
        assert "My Session" in text

    def test_to_summary_text_skips_empty(self) -> None:
        notes = SessionNotes()
        notes.get_section("session_title").content = "Title"
        text = notes.to_summary_text()
        assert "## Current State" not in text

    def test_to_json_includes_meta(self) -> None:
        notes = SessionNotes()
        notes.last_updated_message_idx = 10
        notes.incremental_count = 2
        notes.get_section("current_state").content = "working"
        data = json.loads(notes.to_json())
        assert "_meta" in data
        assert data["_meta"]["last_updated_message_idx"] == 10
        assert data["_meta"]["incremental_count"] == 2
        assert data["current_state"] == "working"

    def test_from_json_restores_meta(self) -> None:
        notes = SessionNotes()
        notes.last_updated_message_idx = 42
        notes.incremental_count = 3
        notes.get_section("task_spec").content = "build feature"
        json_str = notes.to_json()

        restored = SessionNotes.from_json(json_str)
        assert restored.last_updated_message_idx == 42
        assert restored.incremental_count == 3
        assert restored.get_section("task_spec").content == "build feature"

    def test_from_json_backward_compatible(self) -> None:
        old_json = json.dumps({"current_state": "test", "task_spec": "test"})
        notes = SessionNotes.from_json(old_json)
        assert notes.last_updated_message_idx == 0
        assert notes.incremental_count == 0
        assert notes.get_section("current_state").content == "test"

    def test_from_json_ignores_unknown_keys(self) -> None:
        data = {"current_state": "test", "unknown_key": "ignored"}
        notes = SessionNotes.from_json(json.dumps(data))
        assert notes.get_section("current_state").content == "test"

    def test_get_section(self) -> None:
        notes = SessionNotes()
        assert notes.get_section("current_state") is not None
        assert notes.get_section("nonexistent") is None

    def test_truncate_for_compact(self) -> None:
        notes = SessionNotes()
        notes.get_section("session_title").content = "Title"
        text, truncated = notes.truncate_for_compact()
        assert "Title" in text
        assert not truncated

    def test_truncate_for_compact_truncates_oversized(self) -> None:
        notes = SessionNotes()
        notes.get_section("session_title").content = "x" * 10000
        text, truncated = notes.truncate_for_compact()
        assert truncated
        assert "[... section truncated for length ...]" in text

    def test_needs_full_refresh(self) -> None:
        notes = SessionNotes()
        assert not notes.needs_full_refresh()
        notes.incremental_count = 5
        assert notes.needs_full_refresh()


# ---------------------------------------------------------------------------
# trigger.py
# ---------------------------------------------------------------------------


class TestSessionNotesTrigger:
    def test_no_trigger_below_init_threshold(self) -> None:
        trigger = SessionNotesTrigger(SessionNotesConfig(init_token_threshold=8000))
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        assert not trigger.should_update(msgs, total_tokens=1000, total_tool_calls=0)

    def test_first_trigger_at_init_threshold(self) -> None:
        trigger = SessionNotesTrigger(SessionNotesConfig(init_token_threshold=1000))
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        assert trigger.should_update(msgs, total_tokens=1000, total_tool_calls=0)

    def test_no_trigger_below_update_threshold(self) -> None:
        cfg = SessionNotesConfig(init_token_threshold=100, update_token_threshold=5000, update_tool_call_threshold=3)
        trigger = SessionNotesTrigger(cfg)
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        trigger.should_update(msgs, total_tokens=100, total_tool_calls=0)
        assert not trigger.should_update(msgs, total_tokens=200, total_tool_calls=5)

    def test_trigger_on_token_and_tool_call_growth(self) -> None:
        cfg = SessionNotesConfig(init_token_threshold=100, update_token_threshold=500, update_tool_call_threshold=2)
        trigger = SessionNotesTrigger(cfg)
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        trigger.should_update(msgs, total_tokens=100, total_tool_calls=0)
        assert trigger.should_update(msgs, total_tokens=700, total_tool_calls=3)

    def test_trigger_on_natural_break(self) -> None:
        cfg = SessionNotesConfig(init_token_threshold=100, update_token_threshold=500, update_tool_call_threshold=10)
        trigger = SessionNotesTrigger(cfg)
        msgs: list[BaseMessage] = [HumanMessage(content="hi"), AIMessage(content="done")]
        trigger.should_update(msgs, total_tokens=100, total_tool_calls=0)
        assert trigger.should_update(msgs, total_tokens=700, total_tool_calls=0)

    def test_no_trigger_on_natural_break_below_token_threshold(self) -> None:
        cfg = SessionNotesConfig(init_token_threshold=100, update_token_threshold=500, update_tool_call_threshold=10)
        trigger = SessionNotesTrigger(cfg)
        msgs: list[BaseMessage] = [HumanMessage(content="hi"), AIMessage(content="done")]
        trigger.should_update(msgs, total_tokens=100, total_tool_calls=0)
        assert not trigger.should_update(msgs, total_tokens=200, total_tool_calls=0)

    def test_record_update(self) -> None:
        cfg = SessionNotesConfig(init_token_threshold=100, update_token_threshold=500, update_tool_call_threshold=2)
        trigger = SessionNotesTrigger(cfg)
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        trigger.should_update(msgs, total_tokens=100, total_tool_calls=0)
        trigger.record_update(total_tokens=5000, total_tool_calls=10)
        assert not trigger.should_update(msgs, total_tokens=5100, total_tool_calls=10)

    def test_reset(self) -> None:
        trigger = SessionNotesTrigger(SessionNotesConfig(init_token_threshold=100))
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        trigger.should_update(msgs, total_tokens=100, total_tool_calls=0)
        trigger.reset()
        assert not trigger.should_update(msgs, total_tokens=50, total_tool_calls=0)

    def test_should_update_notes_convenience(self) -> None:
        trigger = SessionNotesTrigger(SessionNotesConfig(init_token_threshold=100))
        msgs: list[BaseMessage] = [HumanMessage(content="hi")]
        assert should_update_notes(trigger, msgs, total_tokens=100, total_tool_calls=0)


# ---------------------------------------------------------------------------
# updater.py
# ---------------------------------------------------------------------------


class TestSessionNotesManager:
    @pytest.fixture()
    def mock_llm(self) -> MagicMock:
        llm = MagicMock()
        response = MagicMock()
        response.content = json.dumps(
            {
                "session_title": "Test Session",
                "current_state": "Working on tests",
                "task_spec": "Write unit tests",
            }
        )
        llm.ainvoke = AsyncMock(return_value=response)
        return llm

    @pytest.fixture()
    def small_config(self) -> SessionNotesConfig:
        return SessionNotesConfig(
            init_token_threshold=100,
            update_token_threshold=50,
            update_tool_call_threshold=1,
            full_refresh_interval=3,
            max_consecutive_failures=2,
            wait_timeout_seconds=1.0,
        )

    @pytest.mark.asyncio()
    async def test_maybe_trigger_update(self, mock_llm: MagicMock, small_config: SessionNotesConfig) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = SessionNotesManager(llm=mock_llm, config=small_config)
        msgs: list[BaseMessage] = [HumanMessage(content="hello world " * 100)]

        await manager.maybe_trigger_update(msgs, total_tokens=200, total_tool_calls=0)
        await asyncio.sleep(0.1)

        assert mock_llm.ainvoke.called
        assert manager.notes.get_section("session_title").content == "Test Session"

    @pytest.mark.asyncio()
    async def test_circuit_breaker(self, small_config: SessionNotesConfig) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM error"))
        manager = SessionNotesManager(llm=llm, config=small_config)
        msgs: list[BaseMessage] = [HumanMessage(content="hello " * 100)]

        await manager.maybe_trigger_update(msgs, total_tokens=200, total_tool_calls=0)
        await asyncio.sleep(0.1)
        assert manager._consecutive_failures >= 1

        manager._trigger.reset()
        manager._trigger._initialized = True
        manager._trigger._last_token_count = 200
        await manager.maybe_trigger_update(msgs, total_tokens=400, total_tool_calls=2)
        await asyncio.sleep(0.1)

        manager._trigger.reset()
        manager._trigger._initialized = True
        manager._trigger._last_token_count = 400

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.context_management.strategies.session_notes.updater.time.time")
    async def test_circuit_breaker_cooldown_recovery(self, mock_time, small_config: SessionNotesConfig) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM error"))
        manager = SessionNotesManager(llm=llm, config=small_config)
        msgs: list[BaseMessage] = [HumanMessage(content="hello " * 100)]

        # Trip the circuit breaker
        mock_time.return_value = 1000.0
        for _ in range(small_config.max_consecutive_failures):
            manager._trigger.reset()
            manager._trigger._initialized = True
            manager._trigger._last_token_count = 0
            await manager.maybe_trigger_update(msgs, total_tokens=200, total_tool_calls=0)
            await asyncio.sleep(0.1)

        assert manager._consecutive_failures == small_config.max_consecutive_failures
        assert manager._is_circuit_open() is True

        # Advance time past cooldown
        mock_time.return_value = 1000.0 + small_config.circuit_breaker_cooldown_seconds + 1.0

        # Should auto-recover
        assert manager._is_circuit_open() is False
        assert manager._consecutive_failures == 0
        assert manager._circuit_open_time == 0.0

    @pytest.mark.asyncio
    async def test_circuit_breaker_auth_failure(self, small_config: SessionNotesConfig) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=Exception("401 Unauthorized"))
        manager = SessionNotesManager(llm=llm, config=small_config)
        msgs: list[BaseMessage] = [HumanMessage(content="hello " * 100)]

        await manager.maybe_trigger_update(msgs, total_tokens=200, total_tool_calls=0)
        await asyncio.sleep(0.1)

        # Auth failure should trip circuit breaker immediately
        assert manager._consecutive_failures == small_config.max_consecutive_failures
        assert manager._is_circuit_open() is True
        await manager.maybe_trigger_update(msgs, total_tokens=600, total_tool_calls=4)
        await asyncio.sleep(0.1)

        assert manager._consecutive_failures >= small_config.max_consecutive_failures

    @pytest.mark.asyncio()
    async def test_wait_for_update_no_op(self, mock_llm: MagicMock, small_config: SessionNotesConfig) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = SessionNotesManager(llm=mock_llm, config=small_config)
        await manager.wait_for_update()

    @pytest.mark.asyncio()
    async def test_load_from_json(self, mock_llm: MagicMock, small_config: SessionNotesConfig) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = SessionNotesManager(llm=mock_llm, config=small_config)
        notes = SessionNotes()
        notes.last_updated_message_idx = 10
        notes.incremental_count = 2
        notes.get_section("current_state").content = "loaded state"
        manager.load_from_json(notes.to_json())

        assert manager.notes.last_updated_message_idx == 10
        assert manager.notes.incremental_count == 2
        assert manager.notes.get_section("current_state").content == "loaded state"

    @pytest.mark.asyncio()
    async def test_full_refresh_after_n_incremental(self, mock_llm: MagicMock) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        cfg = SessionNotesConfig(
            init_token_threshold=100, update_token_threshold=50, update_tool_call_threshold=1, full_refresh_interval=2
        )
        manager = SessionNotesManager(llm=mock_llm, config=cfg)
        manager._notes.incremental_count = 2

        msgs: list[BaseMessage] = [HumanMessage(content="hello " * 100)]
        await manager.maybe_trigger_update(msgs, total_tokens=200, total_tool_calls=0)
        await asyncio.sleep(0.1)

        assert manager.notes.incremental_count == 0


# ---------------------------------------------------------------------------
# updater.py - _truncate_messages_for_update
# ---------------------------------------------------------------------------


class TestTruncateMessages:
    def test_no_truncation_needed(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import (
            _truncate_messages_for_update,
        )

        msgs: list[BaseMessage] = [HumanMessage(content="short")]
        result = _truncate_messages_for_update(msgs, max_chars=1000)
        assert len(result) == 1

    def test_truncation_keeps_recent(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import (
            _truncate_messages_for_update,
        )

        msgs: list[BaseMessage] = [
            HumanMessage(content="a" * 500),
            HumanMessage(content="b" * 500),
            HumanMessage(content="c" * 500),
        ]
        result = _truncate_messages_for_update(msgs, max_chars=1000)
        assert len(result) == 2
        assert result[0].content == "b" * 500
        assert result[1].content == "c" * 500

    def test_empty_messages(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import (
            _truncate_messages_for_update,
        )

        result = _truncate_messages_for_update([], max_chars=1000)
        assert result == []


# ---------------------------------------------------------------------------
# updater.py - _parse_notes_response
# ---------------------------------------------------------------------------


class TestParseNotesResponse:
    def test_parse_json_block(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import _parse_notes_response

        content = '```json\n{"session_title": "Test"}\n```'
        result = _parse_notes_response(content)
        assert result == {"session_title": "Test"}

    def test_parse_raw_json(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import _parse_notes_response

        content = '{"session_title": "Test"}'
        result = _parse_notes_response(content)
        assert result == {"session_title": "Test"}

    def test_parse_invalid(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import _parse_notes_response

        assert _parse_notes_response("not json at all") is None


# ---------------------------------------------------------------------------
# session_notes_processor.py
# ---------------------------------------------------------------------------


class TestSessionNotesProcessor:
    @pytest.fixture()
    def mock_manager(self) -> MagicMock:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = MagicMock(spec=SessionNotesManager)
        notes = SessionNotes()
        content = "x" * (MIN_READY_TOKENS * 4)
        notes.get_section("current_state").content = content
        notes.get_section("task_spec").content = content
        notes.last_updated_message_idx = 5
        manager.notes = notes
        manager.wait_for_update = AsyncMock()
        return manager

    @pytest.mark.asyncio()
    async def test_should_process_false_below_threshold(self, mock_manager: MagicMock) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            SessionNotesProcessor,
        )

        processor = SessionNotesProcessor(manager=mock_manager, summarize_trigger_threshold=100000)
        context = ProcessorContext(messages=[HumanMessage(content="short")], user_query="")
        assert not await processor.should_process(context)

    @pytest.mark.asyncio()
    async def test_should_process_false_notes_not_ready(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            SessionNotesProcessor,
        )
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = MagicMock(spec=SessionNotesManager)
        manager.notes = SessionNotes()
        processor = SessionNotesProcessor(manager=manager, summarize_trigger_threshold=10)
        context = ProcessorContext(messages=[HumanMessage(content="x" * 1000)], user_query="")
        assert not await processor.should_process(context)

    @pytest.mark.asyncio()
    async def test_process_replaces_messages(self, mock_manager: MagicMock) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            SessionNotesProcessor,
        )
        from myrm_agent_harness.agent.context_management.strategies.summary_builder import UNVERIFIED_CONTEXT_MARKER

        processor = SessionNotesProcessor(manager=mock_manager, summarize_trigger_threshold=10)
        messages: list[BaseMessage] = [
            SystemMessage(content="system prompt " * 1000),
            HumanMessage(content="old message content " * 2000),
            AIMessage(content="old response content " * 2000),
            HumanMessage(content="middle message " * 5000),
            AIMessage(content="middle response " * 5000),
            HumanMessage(content="another middle message " * 5000),
            AIMessage(content="another middle response " * 5000),
            HumanMessage(content="recent question"),
            AIMessage(content="recent answer"),
        ]
        context = ProcessorContext(messages=messages, user_query="")
        result = await processor.process(context)

        assert result.tokens_saved > 0
        assert result.structured_summary is not None
        assert any("Session Notes Summary" in m.content for m in result.messages if isinstance(m.content, str))
        assert any(UNVERIFIED_CONTEXT_MARKER in m.content for m in result.messages if isinstance(m.content, str))

    @pytest.mark.asyncio()
    async def test_process_falls_through_when_not_ready(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            SessionNotesProcessor,
        )
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = MagicMock(spec=SessionNotesManager)
        manager.notes = SessionNotes()
        manager.wait_for_update = AsyncMock()

        processor = SessionNotesProcessor(manager=manager, summarize_trigger_threshold=10)
        messages: list[BaseMessage] = [HumanMessage(content="test")]
        context = ProcessorContext(messages=messages, user_query="")
        result = await processor.process(context)

        assert result.messages == messages
        assert result.structured_summary is None


# ---------------------------------------------------------------------------
# summarize_processor.py - double compression protection
# ---------------------------------------------------------------------------


class TestSummarizeProcessorSkipsAfterSessionNotes:
    @pytest.mark.asyncio()
    async def test_skips_when_structured_summary_set(self) -> None:
        from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
        from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
        from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
            SummarizeProcessor,
        )

        processor = SummarizeProcessor()
        context = ProcessorContext(messages=[HumanMessage(content="x" * 500000)], user_query="")
        context.structured_summary = StructuredSummary(user_goal="test")
        assert not await processor.should_process(context)


# ---------------------------------------------------------------------------
# prompts.py
# ---------------------------------------------------------------------------


class TestPrompts:
    def test_build_incremental_prompt(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.prompts import (
            build_incremental_prompt,
        )

        notes = SessionNotes()
        notes.get_section("current_state").content = "working"
        prompt = build_incremental_prompt(notes, "New message content")
        assert "New Conversation Content" in prompt
        assert "Current Session Notes" in prompt
        assert "CRITICAL RULES" in prompt

    def test_build_full_refresh_prompt(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.prompts import (
            build_full_refresh_prompt,
        )

        notes = SessionNotes()
        prompt = build_full_refresh_prompt(notes, "Full context")
        assert "Rebuild" in prompt
        assert "Full Conversation Context" in prompt

    def test_section_reminders_when_oversized(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.prompts import (
            build_incremental_prompt,
        )

        notes = SessionNotes()
        notes.get_section("current_state").content = "x" * 20000
        prompt = build_incremental_prompt(notes, "new")
        assert "Size Warnings" in prompt


# ---------------------------------------------------------------------------
# _calculate_keep_index
# ---------------------------------------------------------------------------


class TestCalculateKeepIndex:
    def test_keeps_recent_messages(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _calculate_keep_index,
        )

        msgs: list[BaseMessage] = [
            HumanMessage(content="old " * 100),
            AIMessage(content="old " * 100),
            HumanMessage(content="recent"),
            AIMessage(content="recent"),
        ]
        idx = _calculate_keep_index(msgs, last_summarized_idx=1)
        assert idx >= 0
        assert idx <= len(msgs)

    def test_empty_messages(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _calculate_keep_index,
        )

        assert _calculate_keep_index([], last_summarized_idx=0) == 0

    def test_preserves_tool_pairs(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _calculate_keep_index,
        )

        msgs: list[BaseMessage] = [
            HumanMessage(content="x" * 1000),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "tool", "args": {}}]),
            ToolMessage(content="result", tool_call_id="tc1"),
            HumanMessage(content="follow up"),
            AIMessage(content="response"),
        ]
        idx = _calculate_keep_index(msgs, last_summarized_idx=0)
        kept = msgs[idx:]
        tool_result_ids = {m.tool_call_id for m in kept if isinstance(m, ToolMessage)}
        tool_use_ids: set[str] = set()
        for m in kept:
            if isinstance(m, AIMessage) and m.tool_calls:
                tool_use_ids.update(tc["id"] for tc in m.tool_calls)
        assert tool_result_ids.issubset(tool_use_ids), "Tool result without matching tool use in kept messages"

    def test_max_keep_tokens_cap(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _calculate_keep_index,
        )

        msgs: list[BaseMessage] = [
            HumanMessage(content="old " * 5000),
            AIMessage(content="old " * 5000),
            HumanMessage(content="mid " * 5000),
            AIMessage(content="mid " * 5000),
            HumanMessage(content="recent " * 5000),
            AIMessage(content="recent " * 5000),
        ]
        idx = _calculate_keep_index(msgs, last_summarized_idx=3)
        assert idx >= 0
        assert idx < len(msgs)

    def test_expand_backward_for_min_tokens(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _calculate_keep_index,
        )

        msgs: list[BaseMessage] = [
            HumanMessage(content="old " * 3000),
            AIMessage(content="old " * 3000),
            HumanMessage(content="recent"),
            AIMessage(content="recent"),
        ]
        idx = _calculate_keep_index(msgs, last_summarized_idx=1)
        assert idx <= 2

    def test_adjust_for_orphaned_tool_result(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _calculate_keep_index,
        )

        msgs: list[BaseMessage] = [
            HumanMessage(content="old " * 3000),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "tool", "args": {}}]),
            ToolMessage(content="result " * 3000, tool_call_id="tc1"),
            HumanMessage(content="recent " * 3000),
            AIMessage(content="recent " * 3000),
        ]
        idx = _calculate_keep_index(msgs, last_summarized_idx=0)
        kept = msgs[idx:]
        tool_result_ids = {m.tool_call_id for m in kept if isinstance(m, ToolMessage)}
        tool_use_ids: set[str] = set()
        for m in kept:
            if isinstance(m, AIMessage) and m.tool_calls:
                tool_use_ids.update(tc["id"] for tc in m.tool_calls)
        assert tool_result_ids.issubset(tool_use_ids)


# ---------------------------------------------------------------------------
# _has_text_content
# ---------------------------------------------------------------------------


class TestHasTextContent:
    def test_ai_message_with_list_content(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _has_text_content,
        )

        msg = AIMessage(content=[{"type": "text", "text": "hello"}])
        assert _has_text_content(msg)

    def test_ai_message_with_empty_list(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _has_text_content,
        )

        msg = AIMessage(content=[])
        assert not _has_text_content(msg)

    def test_tool_message_returns_false(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _has_text_content,
        )

        msg = ToolMessage(content="result", tool_call_id="tc1")
        assert not _has_text_content(msg)


# ---------------------------------------------------------------------------
# _extract_lines
# ---------------------------------------------------------------------------


class TestExtractLines:
    def test_basic_extraction(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _extract_lines,
        )

        content = "- item 1\n- item 2\n- item 3"
        lines = _extract_lines(content, max_items=10)
        assert len(lines) == 3
        assert lines[0] == "item 1"

    def test_max_items_limit(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _extract_lines,
        )

        content = "\n".join(f"- item {i}" for i in range(20))
        lines = _extract_lines(content, max_items=5)
        assert len(lines) == 5

    def test_skips_empty_lines(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _extract_lines,
        )

        content = "- item 1\n\n\n- item 2"
        lines = _extract_lines(content)
        assert len(lines) == 2

    def test_strips_markdown_bullets(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _extract_lines,
        )

        content = "• bullet\n* star\n- dash"
        lines = _extract_lines(content)
        assert lines == ["bullet", "star", "dash"]


# ---------------------------------------------------------------------------
# _build_structured_summary
# ---------------------------------------------------------------------------


class TestBuildStructuredSummary:
    def test_builds_from_notes(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _build_structured_summary,
        )

        notes = SessionNotes()
        notes.get_section("task_spec").content = "Build a feature"
        notes.get_section("current_state").content = "Working on tests"
        notes.get_section("worklog").content = "- Step 1\n- Step 2"
        notes.get_section("key_findings").content = "- Finding A\n- Finding B"
        notes.get_section("files_and_functions").content = "- file1.py\n- file2.py"

        summary = _build_structured_summary(notes)
        assert summary.user_goal == "Build a feature"
        assert summary.last_action == "Working on tests"
        assert len(summary.completed_actions) == 2
        assert len(summary.key_findings) == 2
        assert summary.errors_and_fixes == []
        assert len(summary.files_modified) == 2

    def test_builds_errors_and_fixes_from_notes(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _build_structured_summary,
        )

        notes = SessionNotes()
        notes.get_section("task_spec").content = "Fix bugs"
        notes.get_section("current_state").content = "Debugging"
        notes.get_section(
            "errors_and_corrections"
        ).content = "- ImportError -> added __init__.py\n- timeout -> increased deadline"

        summary = _build_structured_summary(notes)
        assert len(summary.errors_and_fixes) == 2
        assert "ImportError -> added __init__.py" in summary.errors_and_fixes[0]


# ---------------------------------------------------------------------------
# updater.py - on_persist callback
# ---------------------------------------------------------------------------


class TestSessionNotesManagerPersist:
    @pytest.mark.asyncio()
    async def test_on_persist_called_after_update(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        persist_mock = AsyncMock()
        llm = MagicMock()
        response = MagicMock()
        response.content = json.dumps(
            {
                "session_title": "Test",
                "current_state": "Working",
            }
        )
        llm.ainvoke = AsyncMock(return_value=response)

        cfg = SessionNotesConfig(init_token_threshold=100, update_token_threshold=50, update_tool_call_threshold=1)
        manager = SessionNotesManager(llm=llm, config=cfg, on_persist=persist_mock)
        msgs: list[BaseMessage] = [HumanMessage(content="hello world " * 100)]

        await manager.maybe_trigger_update(msgs, total_tokens=200, total_tool_calls=0)
        await asyncio.sleep(0.2)

        assert persist_mock.called
        persisted_json = persist_mock.call_args[0][0]
        data = json.loads(persisted_json)
        assert data["session_title"] == "Test"

    @pytest.mark.asyncio()
    async def test_on_persist_failure_does_not_break_update(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        persist_mock = AsyncMock(side_effect=RuntimeError("DB error"))
        llm = MagicMock()
        response = MagicMock()
        response.content = json.dumps({"current_state": "Working"})
        llm.ainvoke = AsyncMock(return_value=response)

        cfg = SessionNotesConfig(init_token_threshold=100, update_token_threshold=50, update_tool_call_threshold=1)
        manager = SessionNotesManager(llm=llm, config=cfg, on_persist=persist_mock)
        msgs: list[BaseMessage] = [HumanMessage(content="hello world " * 100)]

        await manager.maybe_trigger_update(msgs, total_tokens=200, total_tool_calls=0)
        await asyncio.sleep(0.2)

        assert manager.notes.get_section("current_state").content == "Working"
        assert manager._consecutive_failures == 0

    @pytest.mark.asyncio()
    async def test_trailing_run(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        call_count = 0

        async def slow_invoke(msgs: list[BaseMessage], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.15)
            response = MagicMock()
            response.content = json.dumps({"current_state": f"State {call_count}"})
            return response

        llm = MagicMock()
        llm.ainvoke = slow_invoke

        cfg = SessionNotesConfig(init_token_threshold=100, update_token_threshold=50, update_tool_call_threshold=1)
        manager = SessionNotesManager(llm=llm, config=cfg)
        msgs1: list[BaseMessage] = [HumanMessage(content="hello world " * 100)]
        msgs2: list[BaseMessage] = [*msgs1, AIMessage(content="response"), HumanMessage(content="more " * 100)]

        await manager.maybe_trigger_update(msgs1, total_tokens=200, total_tool_calls=0)
        await asyncio.sleep(0.05)

        manager._trigger.reset()
        manager._trigger._initialized = True
        manager._trigger._last_token_count = 200
        await manager.maybe_trigger_update(msgs2, total_tokens=400, total_tool_calls=2)

        await asyncio.sleep(0.8)

        assert call_count >= 2

    @pytest.mark.asyncio()
    async def test_wait_for_update_with_active_update(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        async def slow_invoke(msgs: list[BaseMessage], **kwargs: object) -> MagicMock:
            await asyncio.sleep(0.2)
            response = MagicMock()
            response.content = json.dumps({"current_state": "Done"})
            return response

        llm = MagicMock()
        llm.ainvoke = slow_invoke

        cfg = SessionNotesConfig(
            init_token_threshold=100, update_token_threshold=50, update_tool_call_threshold=1, wait_timeout_seconds=2.0
        )
        manager = SessionNotesManager(llm=llm, config=cfg)
        msgs: list[BaseMessage] = [HumanMessage(content="hello world " * 100)]

        await manager.maybe_trigger_update(msgs, total_tokens=200, total_tool_calls=0)
        await asyncio.sleep(0.05)
        assert manager.is_updating

        await manager.wait_for_update()
        assert not manager.is_updating


# ---------------------------------------------------------------------------
# SessionNotesProcessor - name property and truncated warning
# ---------------------------------------------------------------------------


class TestSessionNotesProcessorName:
    def test_name_property(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            SessionNotesProcessor,
        )
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = MagicMock(spec=SessionNotesManager)
        processor = SessionNotesProcessor(manager=manager)
        assert processor.name == "session_notes"

    @pytest.mark.asyncio()
    async def test_process_with_truncated_notes(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            SessionNotesProcessor,
        )
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = MagicMock(spec=SessionNotesManager)
        notes = SessionNotes()
        content = "x" * (MIN_READY_TOKENS * 4)
        notes.get_section("current_state").content = content
        notes.get_section("task_spec").content = content
        notes.get_section("session_title").content = "x" * 20000
        notes.last_updated_message_idx = 2
        manager.notes = notes
        manager.wait_for_update = AsyncMock()

        processor = SessionNotesProcessor(manager=manager, summarize_trigger_threshold=10)
        messages: list[BaseMessage] = [
            HumanMessage(content="old message content " * 5000),
            AIMessage(content="old response content " * 5000),
            HumanMessage(content="recent question"),
            AIMessage(content="recent answer"),
        ]
        context = ProcessorContext(messages=messages, user_query="")
        result = await processor.process(context)

        assert result.structured_summary is not None
        assert any("Session Notes Summary" in m.content for m in result.messages if isinstance(m.content, str))


class TestSessionNotesProcessorCachePreservation:
    """Cover process() skip paths for Resume and HITL sessions."""

    @pytest.mark.asyncio()
    async def test_skip_for_resume(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            SessionNotesProcessor,
        )
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = MagicMock(spec=SessionNotesManager)
        notes = SessionNotes()
        content = "x" * (MIN_READY_TOKENS * 4)
        notes.get_section("current_state").content = content
        notes.get_section("task_spec").content = content
        manager.notes = notes
        manager.wait_for_update = AsyncMock()

        processor = SessionNotesProcessor(manager=manager, summarize_trigger_threshold=10)
        messages: list[BaseMessage] = [HumanMessage(content="test " * 2000)]
        context = ProcessorContext(messages=messages, user_query="", is_resume=True)
        result = await processor.process(context)
        assert result.messages == messages
        assert result.structured_summary is None

    @pytest.mark.asyncio()
    async def test_skip_for_hitl_session(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            SessionNotesProcessor,
        )
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        manager = MagicMock(spec=SessionNotesManager)
        notes = SessionNotes()
        content = "x" * (MIN_READY_TOKENS * 4)
        notes.get_section("current_state").content = content
        notes.get_section("task_spec").content = content
        manager.notes = notes
        manager.wait_for_update = AsyncMock()

        processor = SessionNotesProcessor(manager=manager, summarize_trigger_threshold=10)
        messages: list[BaseMessage] = [HumanMessage(content="test " * 2000)]
        context = ProcessorContext(
            messages=messages,
            user_query="",
            merged_context={"hitl_session_active": True},
        )
        result = await processor.process(context)
        assert result.messages == messages


class TestSessionNotesProcessorNotifyCompaction:
    """Verify notify_compaction is called during process."""

    @pytest.mark.asyncio()
    @patch("myrm_agent_harness.agent.context_management.infra.cache_break_detector.get_cache_break_detector")
    async def test_notify_compaction_called(self, mock_detector_fn) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            SessionNotesProcessor,
        )
        from myrm_agent_harness.agent.context_management.strategies.session_notes.updater import SessionNotesManager

        mock_detector = MagicMock()
        mock_detector_fn.return_value = mock_detector

        manager = MagicMock(spec=SessionNotesManager)
        notes = SessionNotes()
        content = "x" * (MIN_READY_TOKENS * 4)
        notes.get_section("current_state").content = content
        notes.get_section("task_spec").content = content
        notes.last_updated_message_idx = 2
        manager.notes = notes
        manager.wait_for_update = AsyncMock()

        processor = SessionNotesProcessor(manager=manager, summarize_trigger_threshold=10)
        messages: list[BaseMessage] = [
            SystemMessage(content="system " * 500),
            HumanMessage(content="old " * 5000),
            AIMessage(content="old " * 5000),
            HumanMessage(content="recent"),
            AIMessage(content="recent"),
        ]
        context = ProcessorContext(messages=messages, user_query="")
        result = await processor.process(context)

        assert result.structured_summary is not None
        mock_detector.notify_compaction.assert_called_once()


class TestAnchorLastUserMessage:
    """Cover _anchor_last_user_message edge cases."""

    def test_anchor_when_user_message_before_start(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _anchor_last_user_message,
        )

        msgs: list[BaseMessage] = [
            HumanMessage(content="user msg"),
            AIMessage(content="response 1"),
            AIMessage(content="response 2"),
            AIMessage(content="response 3"),
        ]
        result = _anchor_last_user_message(msgs, start=2)
        assert result == 0

    def test_no_user_message_returns_start(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _anchor_last_user_message,
        )

        msgs: list[BaseMessage] = [
            AIMessage(content="r1"),
            AIMessage(content="r2"),
        ]
        result = _anchor_last_user_message(msgs, start=1)
        assert result == 1

    def test_user_message_in_kept_region(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _anchor_last_user_message,
        )

        msgs: list[BaseMessage] = [
            AIMessage(content="r1"),
            HumanMessage(content="user msg"),
            AIMessage(content="r2"),
        ]
        result = _anchor_last_user_message(msgs, start=1)
        assert result == 1


class TestAdjustForToolPairs:
    """Cover _adjust_for_tool_pairs edge cases."""

    def test_no_tool_results_returns_unchanged(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _adjust_for_tool_pairs,
        )

        msgs: list[BaseMessage] = [
            HumanMessage(content="msg"),
            AIMessage(content="response"),
        ]
        assert _adjust_for_tool_pairs(msgs, 1) == 1

    def test_tool_result_with_matching_use_returns_unchanged(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _adjust_for_tool_pairs,
        )

        msgs: list[BaseMessage] = [
            HumanMessage(content="msg"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "t", "args": {}}]),
            ToolMessage(content="result", tool_call_id="tc1"),
        ]
        assert _adjust_for_tool_pairs(msgs, 1) == 1

    def test_orphaned_tool_result_pulls_back(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _adjust_for_tool_pairs,
        )

        msgs: list[BaseMessage] = [
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "t", "args": {}}]),
            HumanMessage(content="msg"),
            ToolMessage(content="result", tool_call_id="tc1"),
        ]
        result = _adjust_for_tool_pairs(msgs, 1)
        assert result == 0

    def test_start_at_zero_returns_zero(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _adjust_for_tool_pairs,
        )

        msgs: list[BaseMessage] = [ToolMessage(content="r", tool_call_id="tc1")]
        assert _adjust_for_tool_pairs(msgs, 0) == 0

    def test_start_beyond_length_returns_unchanged(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            _adjust_for_tool_pairs,
        )

        msgs: list[BaseMessage] = [HumanMessage(content="msg")]
        assert _adjust_for_tool_pairs(msgs, 5) == 5


class TestCalculateKeepIndexBranches:
    """Cover remaining _calculate_keep_index branches."""

    def test_max_keep_tokens_branch(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            MAX_KEEP_TOKENS,
            _calculate_keep_index,
        )

        big_content = "x" * (MAX_KEEP_TOKENS * 5)
        msgs: list[BaseMessage] = [
            HumanMessage(content="old"),
            AIMessage(content="old"),
            HumanMessage(content=big_content),
            AIMessage(content=big_content),
        ]
        idx = _calculate_keep_index(msgs, last_summarized_idx=1)
        assert idx >= 2

    def test_min_keep_tokens_met_branch(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
            MIN_KEEP_TEXT_MESSAGES,
            MIN_KEEP_TOKENS,
            _calculate_keep_index,
        )

        content_size = (MIN_KEEP_TOKENS * 4) // MIN_KEEP_TEXT_MESSAGES
        content = "x" * content_size
        msgs: list[BaseMessage] = [HumanMessage(content="old")]
        for _ in range(MIN_KEEP_TEXT_MESSAGES + 2):
            msgs.append(HumanMessage(content=content))
            msgs.append(AIMessage(content=content))
        idx = _calculate_keep_index(msgs, last_summarized_idx=0)
        assert idx >= 1
