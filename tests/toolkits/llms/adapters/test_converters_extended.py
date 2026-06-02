"""Extended coverage for adapters.converters without ChatLiteLLM."""

from __future__ import annotations

import json
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import (
    AIMessage,
    ChatMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from langchain_core.messages.base import BaseMessage

from myrm_agent_harness.toolkits.llms.adapters.converters import (
    _parse_tool_call_args,
    convert_dict_to_message,
    convert_message_to_dict,
    create_usage_metadata,
    ensure_arguments_json_string,
    lc_tool_call_to_openai_tool_call,
)


class OddMessage(BaseMessage):
    """Deliberately unsupported BaseMessage subtype for negative-path coverage."""

    type: Literal["odd"] = "odd"


class TestLcToolCallFormat:
    def test_lc_tool_call_to_openai_sorts_keys(self) -> None:
        tc = ToolCall(name="fn", args={"b": 2, "a": 1}, id="call_x")
        out = lc_tool_call_to_openai_tool_call(tc)
        assert out["function"]["arguments"] == json.dumps({"a": 1, "b": 2}, sort_keys=True)


class TestEnsureArgumentsJsonString:
    def test_coerces_dict_none_invalid_str_and_scalar(self) -> None:
        calls: list[dict] = [
            {
                "type": "function",
                "function": {"name": "a", "arguments": {"x": 1}},
            },
            {
                "type": "function",
                "function": {"name": "b", "arguments": None},
            },
            {
                "type": "function",
                "function": {"name": "c", "arguments": "{not json"},
            },
            {
                "type": "function",
                "function": {"name": "d", "arguments": 42},
            },
            {
                "type": "function",
                "function": "not-a-dict",
            },
        ]
        out = ensure_arguments_json_string(calls)
        assert json.loads(out[0]["function"]["arguments"]) == {"x": 1}
        assert out[1]["function"]["arguments"] == "{}"
        assert out[2]["function"]["arguments"] == "{}"
        parsed_d = json.loads(out[3]["function"]["arguments"])
        assert parsed_d == {"value": 42}


class TestConvertMessageToDict:
    def test_chat_human_system_function_tool_roles(self) -> None:
        assert convert_message_to_dict(ChatMessage(role="custom", content="c"))["role"] == "custom"
        assert convert_message_to_dict(HumanMessage(content="h", name="u"))["name"] == "u"
        assert convert_message_to_dict(SystemMessage(content="s"))["role"] == "system"
        fm = FunctionMessage(content="fc", name="f")
        d = convert_message_to_dict(fm)
        assert d["role"] == "function" and d["name"] == "f"
        tm = ToolMessage(content="t", tool_call_id="tid", name="tn")
        td = convert_message_to_dict(tm)
        assert td["role"] == "tool" and td["tool_call_id"] == "tid"

    def test_ai_message_reasoning_function_call_tool_calls_kwargs(self) -> None:
        ai = AIMessage(
            content="x",
            additional_kwargs={
                "reasoning_content": "rc",
                "function_call": {"name": "legacy", "arguments": "{}"},
                "tool_calls": [
                    {
                        "type": "function",
                        "id": "1",
                        "function": {"name": "z", "arguments": {"q": 1}},
                    }
                ],
            },
        )
        d = convert_message_to_dict(ai)
        assert d["reasoning_content"] == "rc"
        assert "function_call" in d
        assert d["tool_calls"][0]["function"]["name"] == "z"

    def test_ai_message_prefers_structured_tool_calls(self) -> None:
        ai = AIMessage(
            content="",
            tool_calls=[ToolCall(name="t", args={"k": True}, id="id1")],
        )
        d = convert_message_to_dict(ai)
        assert d["tool_calls"][0]["function"]["name"] == "t"

    def test_name_from_additional_kwargs(self) -> None:
        ai = AIMessage(content="a", additional_kwargs={"name": "n1"})
        d = convert_message_to_dict(ai)
        assert d.get("name") == "n1"

    def test_unknown_message_type_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown type"):
            convert_message_to_dict(OddMessage(content="z"))


class TestConvertDictToMessage:
    def test_assistant_with_citations_and_custom_role_fallback(self) -> None:
        msg = convert_dict_to_message(
            {
                "role": "assistant",
                "content": "hello",
                "annotations": [
                    {"url": "https://a.example", "title": "A", "start_index": 0, "end_index": 1},
                    {"invalid": True},
                    {"url": "", "title": "skip"},
                ],
            }
        )
        assert isinstance(msg, AIMessage)
        assert msg.additional_kwargs.get("citations")

        fallback = convert_dict_to_message({"role": "developer", "content": "dev"})
        assert isinstance(fallback, ChatMessage)
        assert fallback.role == "developer"

    def test_user_system_tool_roles(self) -> None:
        assert isinstance(convert_dict_to_message({"role": "user", "content": "u"}), HumanMessage)
        assert isinstance(convert_dict_to_message({"role": "system", "content": "s"}), SystemMessage)
        tm = convert_dict_to_message(
            {"role": "tool", "content": "ok", "tool_call_id": "t1", "name": "tool_a"}
        )
        assert isinstance(tm, ToolMessage)

    def test_assistant_function_call_passthrough(self) -> None:
        msg = convert_dict_to_message(
            {
                "role": "assistant",
                "content": "",
                "function_call": {"name": "old", "arguments": "{}"},
            }
        )
        assert isinstance(msg, AIMessage)
        assert msg.additional_kwargs.get("function_call") == {"name": "old", "arguments": "{}"}


class TestParseToolCallArgsHooks:
    def test_parse_tool_call_args_logs_when_unsafe(self) -> None:
        raw = 'oops "command": "rm -rf /tmp/demo" trailing'
        with patch(
            "myrm_agent_harness.toolkits.llms.adapters.converters.logger.warning"
        ) as mock_warn:
            out = _parse_tool_call_args(raw, "bash_tool")
            assert out == {}
            assert mock_warn.called


class TestCreateUsageMetadata:
    def test_defaults_missing_fields_to_zero(self) -> None:
        meta = create_usage_metadata({})
        assert meta["input_tokens"] == 0
        assert meta["output_tokens"] == 0
        assert meta["total_tokens"] == 0


class TestRecoveryMetricsRecording:
    def test_convert_raw_records_recovery_metric_when_non_standard(self) -> None:
        mock_registry = MagicMock()
        degraded_tc = {
            "type": "function",
            "id": "call_abcd12345678901234567890",
            "function": {"name": "bash_tool", "arguments": "{}"},
        }
        with (
            patch(
                "myrm_agent_harness.observability.metrics.registry.metrics_registry",
                mock_registry,
            ),
            patch(
                "myrm_agent_harness.toolkits.llms.adapters.converters.parse_tool_call_arguments_with_recovery",
                return_value=MagicMock(
                    args={"x": 1},
                    strategy="repair_x",
                    degraded=True,
                    safe=True,
                ),
            ),
        ):
            msg = convert_dict_to_message(
                {"role": "assistant", "content": "", "tool_calls": [degraded_tc]},
                tool_schemas=None,
            )
        assert isinstance(msg, AIMessage)
        mock_registry.record_tool_arg_recovery.assert_called()
