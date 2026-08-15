"""Additional tests for dangling_tool_call_middleware sanitizers and sync path.

Covers the pure sanitizer helpers (_coerce_tool_args_object, the three
_sanitize_*_list functions), repair_dangling_tool_calls entry point, and the
sync wrap_model_call path — complementing the main middleware test file.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.tooling.dangling_tool_call_middleware import (
    _coerce_tool_args_object,
    _sanitize_ai_message,
    _sanitize_invalid_tool_calls_list,
    _sanitize_raw_tool_calls_list,
    _sanitize_tool_calls_list,
    _sanitize_tool_name,
    dangling_tool_call_middleware,
    repair_dangling_tool_calls,
)


class TestSanitizeToolName:
    def test_strips_whitespace(self) -> None:
        assert _sanitize_tool_name("  bash_code_execute_tool  ") == "bash_code_execute_tool"

    def test_empty_falls_back(self) -> None:
        assert _sanitize_tool_name("") == "unknown"
        assert _sanitize_tool_name(None) == "unknown"
        assert _sanitize_tool_name("   ") == "unknown"


class TestCoerceToolArgsObject:
    def test_dict_passthrough(self) -> None:
        assert _coerce_tool_args_object({"a": 1}) == {"a": 1}

    def test_json_object_string(self) -> None:
        assert _coerce_tool_args_object('{"a": 1}') == {"a": 1}

    def test_json_array_string(self) -> None:
        assert _coerce_tool_args_object("[1, 2]") == {"items": [1, 2]}

    def test_invalid_json_string(self) -> None:
        assert _coerce_tool_args_object("not-json") == {}

    def test_other_types(self) -> None:
        assert _coerce_tool_args_object(None) == {}
        assert _coerce_tool_args_object(42) == {}
        assert _coerce_tool_args_object("x") == {}


class TestSanitizeToolCallsList:
    def test_non_list_returns_flag(self) -> None:
        calls, changed = _sanitize_tool_calls_list(None)
        assert calls == [] and changed is False
        calls, changed = _sanitize_tool_calls_list("bad")
        assert calls == [] and changed is True

    def test_skips_non_dict_and_missing_id(self) -> None:
        calls, changed = _sanitize_tool_calls_list([42, {"name": "t", "args": {}}])
        assert changed is True
        assert calls == []

    def test_cleans_name_and_args(self) -> None:
        calls, changed = _sanitize_tool_calls_list(
            [{"id": "c1", "name": "", "args": "bad"}],
        )
        assert changed is True
        assert calls[0]["name"] == "unknown"
        assert calls[0]["args"] == {}


class TestSanitizeInvalidToolCallsList:
    def test_non_list(self) -> None:
        calls, changed = _sanitize_invalid_tool_calls_list(None)
        assert calls == [] and changed is False
        calls, changed = _sanitize_invalid_tool_calls_list(123)
        assert calls == [] and changed is True

    def test_skips_invalid_entries(self) -> None:
        calls, changed = _sanitize_invalid_tool_calls_list(["x", {"name": "t"}])
        assert changed is True
        assert calls == []

    def test_normalizes_error_and_args(self) -> None:
        calls, changed = _sanitize_invalid_tool_calls_list(
            [{"id": "c1", "name": "", "error": 42, "args": None}],
        )
        assert changed is True
        assert calls[0]["name"] == "unknown"
        assert calls[0]["error"] is None
        assert calls[0]["args"] == "{}"


class TestSanitizeRawToolCallsList:
    def test_non_list(self) -> None:
        calls, changed = _sanitize_raw_tool_calls_list(None)
        assert calls == [] and changed is False

    def test_skips_invalid_entries(self) -> None:
        calls, changed = _sanitize_raw_tool_calls_list(["x", {"name": "t"}])
        assert changed is True
        assert calls == []

    def test_builds_clean_function(self) -> None:
        calls, changed = _sanitize_raw_tool_calls_list(
            [{"id": "c1", "function": {"name": "", "arguments": None}}],
        )
        assert changed is True
        assert calls[0]["function"]["name"] == "unknown"
        assert calls[0]["function"]["arguments"] == "{}"
        assert calls[0]["type"] == "function"


class TestSanitizeAiMessage:
    def test_non_ai_message_returns_false(self) -> None:
        assert _sanitize_ai_message(HumanMessage(content="hi")) is False

    def test_mutates_invalid_tool_calls_and_raw(self) -> None:
        msg = AIMessage(
            content="",
            tool_calls=[],
            invalid_tool_calls=[{"id": "c1", "name": "", "error": "err", "args": None}],
            additional_kwargs={
                "tool_calls": [{"id": "c2", "function": {"name": "", "arguments": None}}]
            },
        )
        assert _sanitize_ai_message(msg) is True
        assert msg.invalid_tool_calls[0]["name"] == "unknown"
        assert msg.additional_kwargs["tool_calls"][0]["function"]["name"] == "unknown"

    def test_no_change_returns_false(self) -> None:
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "t", "args": {}}],
        )
        assert _sanitize_ai_message(msg) is False


class TestRepairDanglingToolCalls:
    def test_returns_patched(self) -> None:
        messages = [
            HumanMessage(content="go"),
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "search", "args": {}}]),
        ]
        result = repair_dangling_tool_calls(messages)
        assert len(result) == 3
        assert isinstance(result[2], ToolMessage)

    def test_returns_original_when_clean(self) -> None:
        messages = [HumanMessage(content="hi"), AIMessage(content="ok")]
        assert repair_dangling_tool_calls(messages) is messages


class TestSyncWrapModelCall:
    def test_sync_wrap_model_call_patches(self) -> None:
        messages = [
            HumanMessage(content="go"),
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "search", "args": {}}]),
        ]
        sentinel = MagicMock()
        request = MagicMock()
        request.messages = messages
        patched_request = MagicMock()
        request.override.return_value = patched_request

        def handler(req):
            return sentinel

        result = dangling_tool_call_middleware.wrap_model_call(request, handler)
        request.override.assert_called_once()
        assert result is sentinel

    def test_sync_wrap_model_call_no_patch(self) -> None:
        request = MagicMock()
        request.messages = [HumanMessage(content="hi")]
        sentinel = MagicMock()

        def handler(req):
            assert req is request
            return sentinel

        result = dangling_tool_call_middleware.wrap_model_call(request, handler)
        request.override.assert_not_called()
        assert result is sentinel
