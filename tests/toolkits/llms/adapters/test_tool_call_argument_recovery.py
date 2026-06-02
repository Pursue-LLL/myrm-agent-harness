"""Tests for resilient tool-call argument recovery."""

import json

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.converters import (
    _parse_tool_call_args,
    convert_dict_to_message,
)
from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    parse_tool_call_arguments_with_recovery,
)


def _build_tool_schema(
    name: str, properties: dict[str, object], required: list[str] | None = None
) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


class TestToolArgumentRecovery:
    def test_long_text_field_repair_uses_schema(self) -> None:
        schema = _build_tool_schema(
            "file_write_tool",
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            required=["path", "content"],
        )
        raw = '{"path":"demo.py","content":"print("hello")\nprint("world")"}'

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool", schema)

        assert result.safe is True
        assert result.degraded is False
        assert result.strategy.startswith("long_text_field_repair")
        assert result.args["content"] == 'print("hello")\nprint("world")'

    def test_truncated_json_completion_recovers_required_fields(self) -> None:
        schema = _build_tool_schema(
            "file_write_tool",
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            required=["path", "content"],
        )
        raw = '{"path":"demo.py","content":"print(1)'

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool", schema)

        assert result.safe is True
        assert "truncated" in result.strategy
        assert result.args == {"path": "demo.py", "content": "print(1)"}

    def test_regex_fallback_is_marked_unsafe_without_schema(self) -> None:
        raw = 'oops "command": "rm -rf /tmp/demo" trailing'

        result = parse_tool_call_arguments_with_recovery(raw, "bash_tool")

        assert result.degraded is True
        assert result.strategy == "regex_fallback"
        assert result.safe is False
        assert result.args["command"] == "rm -rf /tmp/demo"

    def test_parse_tool_call_args_drops_unsafe_partial_result(self) -> None:
        raw = 'oops "command": "rm -rf /tmp/demo" trailing'

        parsed = _parse_tool_call_args(raw, "bash_tool")

        assert parsed == {}


class TestConvertDictToMessageRecovery:
    def test_convert_dict_to_message_attaches_recovery_metadata(self) -> None:
        schema = _build_tool_schema(
            "file_write_tool",
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            required=["path", "content"],
        )
        payload = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "file_write_tool",
                        "arguments": '{"path":"demo.py","content":"print("hello")"}',
                    },
                }
            ],
        }

        message = convert_dict_to_message(
            payload,
            available_tools=["file_write_tool"],
            tool_schemas={"file_write_tool": schema},
        )

        assert message.tool_calls[0]["args"]["content"] == 'print("hello")'
        assert message.additional_kwargs["tool_call_recovery"][0]["strategy"].startswith("long_text_field_repair")


class TestStreamFinalizationRecovery:
    def test_final_tool_call_chunk_uses_recovered_and_decoded_args(self) -> None:
        schema = _build_tool_schema(
            "bash_tool",
            {
                "command": {"type": "string"},
            },
            required=["command"],
        )
        model = ChatLiteLLM.model_construct(client=object(), model="test-model")
        raw_tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "bash_tool",
                    "arguments": json.dumps({"command": 'echo "hi" &amp;&amp; ls'}),
                },
            }
        ]

        final_chunk, corrected_tool_calls, recovery_metadata = model._build_final_tool_call_chunk(
            raw_tool_calls,
            {"bash_tool": schema},
        )

        assert final_chunk is not None
        assert corrected_tool_calls[0]["function"]["arguments"] == json.dumps(
            {"command": 'echo "hi" && ls'},
            ensure_ascii=False,
            sort_keys=True,
        )
        assert final_chunk.message.tool_calls[0]["args"]["command"] == 'echo "hi" && ls'
        assert recovery_metadata[0]["safe"] is True

    def test_python_none_to_json_null_recovery(self) -> None:
        """Test that Python 'None' literal is converted to JSON 'null'."""
        raw = '{"path": "demo.py", "content": None}'

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool")

        assert result.strategy == "python_none_to_null"
        assert result.degraded is True
        assert result.safe is True
        assert result.args == {"path": "demo.py", "content": None}

    def test_remove_excess_closing_braces(self) -> None:
        """Test that excess closing braces are removed."""
        raw = '{"path": "demo.py", "content": "hello"}}}}'

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool")

        assert result.strategy in ("remove_excess_closing", "malformed_json_extraction")
        assert result.degraded in (True, False)
        assert result.safe is True
        assert result.args == {"path": "demo.py", "content": "hello"}

    def test_remove_excess_closing_brackets(self) -> None:
        """Test that excess closing brackets are removed."""
        raw = '{"items": ["a", "b", "c"]}]]]'

        result = parse_tool_call_arguments_with_recovery(raw, "list_tool")

        assert result.strategy in ("remove_excess_closing", "malformed_json_extraction")
        assert result.degraded in (True, False)
        assert result.safe is True
        assert result.args == {"items": ["a", "b", "c"]}
