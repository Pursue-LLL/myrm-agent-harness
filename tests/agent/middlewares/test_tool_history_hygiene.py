"""Tests for tool_history_hygiene middleware."""

from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.tool_history_hygiene import (
    _dedup_tool_messages,
    _uniquify_cross_turn_tool_call_ids,
    sanitize_tool_history,
    tool_history_hygiene_middleware,
)
from myrm_agent_harness.toolkits.llms.errors.classifier import classify_failover_reason
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason


class TestDedupToolMessages:
    def test_moonshot_pattern_keeps_last_tool_message(self) -> None:
        messages = [
            HumanMessage(content="store memory"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "memory_store:0", "name": "memory_store", "args": {"k": "a"}}
                ],
            ),
            ToolMessage(content="stored a", tool_call_id="memory_store:0", name="memory_store"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "memory_store:0", "name": "memory_store", "args": {"k": "b"}}
                ],
            ),
            ToolMessage(content="stored b", tool_call_id="memory_store:0", name="memory_store"),
        ]
        deduped = _dedup_tool_messages(messages)
        assert deduped is not None
        tool_messages = [m for m in deduped if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "stored b"


class TestWithinMessageUniquify:
    def test_reids_duplicate_ids_within_same_ai_message(self) -> None:
        messages = [
            HumanMessage(content="run tools"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "call_abc", "name": "bash", "args": {"command": "ls"}},
                    {"id": "call_abc", "name": "file_read_tool", "args": {"path": "a.txt"}},
                ],
            ),
            ToolMessage(content="listed", tool_call_id="call_abc", name="bash"),
            ToolMessage(content="file", tool_call_id="call_abc", name="file_read_tool"),
        ]
        sanitized = sanitize_tool_history(messages)
        assert sanitized is not messages

        ai = next(m for m in sanitized if isinstance(m, AIMessage) and m.tool_calls)
        assert ai.tool_calls[0]["id"] == "call_abc"
        assert ai.tool_calls[1]["id"] == "call_abc@2"

        tool_messages = [m for m in sanitized if isinstance(m, ToolMessage)]
        assert tool_messages[0].tool_call_id == "call_abc"
        assert tool_messages[1].tool_call_id == "call_abc@2"

    def test_reids_duplicate_invalid_tool_calls_within_message(self) -> None:
        messages = [
            AIMessage(
                content="",
                invalid_tool_calls=[
                    {"id": "bad:1", "name": "grep_tool", "error": "parse error"},
                    {"id": "bad:1", "name": "bash", "error": "parse error"},
                ],
            ),
        ]
        sanitized = sanitize_tool_history(messages)
        assert sanitized is not messages
        ai = sanitized[0]
        assert isinstance(ai, AIMessage)
        assert ai.invalid_tool_calls[0]["id"] == "bad:1"
        assert ai.invalid_tool_calls[1]["id"] == "bad:1@2"

    def test_reids_duplicate_additional_kwargs_tool_calls(self) -> None:
        messages = [
            AIMessage(
                content="",
                additional_kwargs={
                    "tool_calls": [
                        {"id": "raw:1", "function": {"name": "a", "arguments": "{}"}},
                        {"id": "raw:1", "function": {"name": "b", "arguments": "{}"}},
                    ]
                },
            ),
        ]
        sanitized = sanitize_tool_history(messages)
        assert sanitized is not messages
        raw_calls = sanitized[0].additional_kwargs["tool_calls"]
        assert raw_calls[0]["id"] == "raw:1"
        assert raw_calls[1]["id"] == "raw:1@2"

    def test_has_tool_content_via_invalid_tool_calls_only(self) -> None:
        messages = [
            AIMessage(
                content="",
                invalid_tool_calls=[{"id": "only:1", "name": "bash", "error": "x"}],
            ),
        ]
        assert sanitize_tool_history(messages) is messages


class TestCrossTurnUniquify:
    def test_reids_duplicate_ids_across_ai_messages(self) -> None:
        messages = [
            HumanMessage(content="first"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_abc", "name": "grep_tool", "args": {"q": "a"}}],
            ),
            ToolMessage(content="hits a", tool_call_id="call_abc", name="grep_tool"),
            AIMessage(content="done"),
            HumanMessage(content="second"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_abc", "name": "grep_tool", "args": {"q": "b"}}],
            ),
            ToolMessage(content="hits b", tool_call_id="call_abc", name="grep_tool"),
        ]
        uniquified = _uniquify_cross_turn_tool_call_ids(messages)
        assert uniquified is not None

        ai_messages = [m for m in uniquified if isinstance(m, AIMessage) and m.tool_calls]
        assert ai_messages[0].tool_calls[0]["id"] == "call_abc"
        assert ai_messages[1].tool_calls[0]["id"] == "call_abc@2"

        tool_messages = [m for m in uniquified if isinstance(m, ToolMessage)]
        assert tool_messages[0].tool_call_id == "call_abc"
        assert tool_messages[1].tool_call_id == "call_abc@2"

    def test_no_change_when_ids_unique(self) -> None:
        messages = [
            HumanMessage(content="hello"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "grep_tool", "args": {}}],
            ),
            ToolMessage(content="ok", tool_call_id="call_1", name="grep_tool"),
        ]
        assert _uniquify_cross_turn_tool_call_ids(messages) is None


    def test_third_occurrence_gets_suffix_at3(self) -> None:
        messages: list[BaseMessage] = []
        for turn in range(3):
            messages.append(
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call_x", "name": "grep_tool", "args": {}}],
                )
            )
            messages.append(
                ToolMessage(content=f"r{turn}", tool_call_id="call_x", name="grep_tool")
            )
        sanitized = sanitize_tool_history(messages)
        ai_ids = [
            m.tool_calls[0]["id"]
            for m in sanitized
            if isinstance(m, AIMessage) and m.tool_calls
        ]
        assert ai_ids == ["call_x", "call_x@2", "call_x@3"]


    def test_cross_turn_reid_via_invalid_tool_calls(self) -> None:
        messages = [
            AIMessage(
                content="",
                invalid_tool_calls=[{"id": "bad:0", "name": "bash", "error": "e"}],
            ),
            ToolMessage(content="r1", tool_call_id="bad:0", name="bash"),
            AIMessage(
                content="",
                invalid_tool_calls=[{"id": "bad:0", "name": "bash", "error": "e2"}],
            ),
            ToolMessage(content="r2", tool_call_id="bad:0", name="bash"),
        ]
        sanitized = sanitize_tool_history(messages)
        invalid_ids = [
            m.invalid_tool_calls[0]["id"]
            for m in sanitized
            if isinstance(m, AIMessage) and m.invalid_tool_calls
        ]
        assert invalid_ids == ["bad:0", "bad:0@2"]
        tool_messages = [m for m in sanitized if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "bad:0@2"
        assert tool_messages[0].content == "r2"

    def test_cross_turn_reid_via_additional_kwargs_only(self) -> None:
        messages = [
            AIMessage(
                content="",
                additional_kwargs={
                    "tool_calls": [
                        {"id": "raw:0", "function": {"name": "a", "arguments": "{}"}}
                    ]
                },
            ),
            ToolMessage(content="r1", tool_call_id="raw:0", name="a"),
            AIMessage(
                content="",
                additional_kwargs={
                    "tool_calls": [
                        {"id": "raw:0", "function": {"name": "b", "arguments": "{}"}}
                    ]
                },
            ),
            ToolMessage(content="r2", tool_call_id="raw:0", name="b"),
        ]
        sanitized = sanitize_tool_history(messages)
        raw_ids = [
            m.additional_kwargs["tool_calls"][0]["id"]
            for m in sanitized
            if isinstance(m, AIMessage) and m.additional_kwargs.get("tool_calls")
        ]
        assert raw_ids == ["raw:0", "raw:0@2"]


class TestSanitizeToolHistory:
    def test_text_only_early_exit(self) -> None:
        messages = [
            HumanMessage(content="hello"),
            AIMessage(content="hi there"),
        ]
        assert sanitize_tool_history(messages) is messages

    def test_combined_dedup_and_uniquify(self) -> None:
        messages = [
            AIMessage(
                content="",
                tool_calls=[{"id": "shared:0", "name": "memory_store", "args": {}}],
            ),
            ToolMessage(content="old", tool_call_id="shared:0", name="memory_store"),
            AIMessage(
                content="",
                tool_calls=[{"id": "shared:0", "name": "memory_store", "args": {}}],
            ),
            ToolMessage(content="new", tool_call_id="shared:0", name="memory_store"),
        ]
        sanitized = sanitize_tool_history(messages)
        assert sanitized is not messages
        tool_messages = [m for m in sanitized if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "new"

        ai_with_tools = [m for m in sanitized if isinstance(m, AIMessage) and m.tool_calls]
        ids = [m.tool_calls[0]["id"] for m in ai_with_tools]
        assert ids == ["shared:0", "shared:0@2"]
        assert tool_messages[0].tool_call_id == "shared:0@2"


class TestToolHistoryHygieneMiddleware:
    async def test_awrap_model_call_sanitizes_request(self) -> None:
        messages = [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_x", "name": "grep_tool", "args": {}}],
            ),
            ToolMessage(content="a", tool_call_id="call_x", name="grep_tool"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_x", "name": "grep_tool", "args": {}}],
            ),
            ToolMessage(content="b", tool_call_id="call_x", name="grep_tool"),
        ]
        request = MagicMock()
        request.messages = messages
        overridden = MagicMock()
        request.override.return_value = overridden
        handler = AsyncMock(return_value="ok")

        result = await tool_history_hygiene_middleware.awrap_model_call(request, handler)

        request.override.assert_called_once()
        passed_messages = request.override.call_args.kwargs["messages"]
        ai_ids = [
            m.tool_calls[0]["id"]
            for m in passed_messages
            if isinstance(m, AIMessage) and m.tool_calls
        ]
        assert ai_ids == ["call_x", "call_x@2"]
        handler.assert_awaited_once_with(overridden)
        assert result == "ok"

    async def test_awrap_model_call_noop_for_text_only(self) -> None:
        messages = [HumanMessage(content="hello"), AIMessage(content="hi")]
        request = MagicMock()
        request.messages = messages
        handler = AsyncMock(return_value="ok")

        await tool_history_hygiene_middleware.awrap_model_call(request, handler)

        request.override.assert_not_called()
        handler.assert_awaited_once_with(request)

    def test_wrap_model_call_sync_sanitizes_request(self) -> None:
        messages = [
            AIMessage(
                content="",
                tool_calls=[{"id": "call_x", "name": "grep_tool", "args": {}}],
            ),
            ToolMessage(content="a", tool_call_id="call_x", name="grep_tool"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_x", "name": "grep_tool", "args": {}}],
            ),
            ToolMessage(content="b", tool_call_id="call_x", name="grep_tool"),
        ]
        request = MagicMock()
        request.messages = messages
        overridden = MagicMock()
        request.override.return_value = overridden
        handler = MagicMock(return_value="ok")

        result = tool_history_hygiene_middleware.wrap_model_call(request, handler)

        request.override.assert_called_once()
        handler.assert_called_once_with(overridden)
        assert result == "ok"


class TestDuplicateToolUseClassifier:
    def test_classifies_anthropic_duplicate_tool_use_error(self) -> None:
        exc = _FakeStatusError(
            "messages.3.content.1.tool_use.id: tool_use ids must be unique within a request",
            status_code=400,
        )
        assert classify_failover_reason(exc) == FailoverReason.DUPLICATE_TOOL_USE_ID

    def test_classifies_openai_style_duplicate_tool_call_id(self) -> None:
        exc = _FakeStatusError("Duplicate tool_call_id found: call_abc", status_code=400)
        assert classify_failover_reason(exc) == FailoverReason.DUPLICATE_TOOL_USE_ID

    def test_non_400_duplicate_phrase_not_classified(self) -> None:
        exc = _FakeStatusError("Duplicate tool_call_id found: call_abc", status_code=500)
        assert classify_failover_reason(exc) != FailoverReason.DUPLICATE_TOOL_USE_ID


class _FakeStatusError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
