"""Tests for resilient tool-call argument recovery."""

import json
import time

import pytest

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.converters import (
    _parse_tool_call_args,
    convert_dict_to_message,
)
from myrm_agent_harness.toolkits.llms.adapters.tool_recovery import (
    build_final_tool_call_chunk,
    has_withheld_tool_calls,
    recover_tool_call_payloads,
)
from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    _NONE_OUTSIDE_STRINGS,
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
        raw = '{"path":"demo.py","content":"print(1)"'

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool", schema)

        assert result.safe is True
        assert "truncated" in result.strategy
        assert result.args == {"path": "demo.py", "content": "print(1)"}

    @pytest.mark.parametrize(
        "raw",
        [
            '{"path":"demo.py","content":"print(1)',
            '{"command":"rm -rf /tmp/cache/old_',
            '{"items":["a","b',
            '{"outer":{"inner":"te',
            '{"content":"ends with a backslash\\',
        ],
    )
    def test_value_cut_off_inside_a_string_is_refused(self, raw: str) -> None:
        """A closed prefix of a path/command/body is a valid but shorter value — never executable."""
        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool")

        assert result.safe is False
        assert result.strategy == "truncated_mid_value"
        assert result.args == {}

    @pytest.mark.parametrize("stream_complete", [None, True])
    def test_provider_reporting_a_normal_finish_cannot_smuggle_a_cut_string(self, stream_complete: bool | None) -> None:
        raw = '{"path":"/etc/pas'

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool", stream_complete=stream_complete)

        assert result.safe is False

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ('{"path":"a.py"', {"path": "a.py"}),
            ('{"a":"x",', {"a": "x"}),
            ('{"items":[1,2', {"items": [1, 2]}),
            ('{"flag":tr', {"flag": True}),
            ('{"ratio":0.', {"ratio": 0.0}),
            ('{"mode":', {"mode": None}),
        ],
    )
    def test_value_cut_at_a_boundary_is_still_completed(self, raw: str, expected: dict[str, object]) -> None:
        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool")

        assert result.safe is True
        assert result.args == expected

    def test_long_text_repair_does_not_close_a_later_cut_string(self) -> None:
        schema = _build_tool_schema(
            "file_write_tool",
            {"path": {"type": "string"}, "content": {"type": "string"}},
            required=["path", "content"],
        )
        cut = '{"content":"complete body","path":"/tmp/x'

        refused = parse_tool_call_arguments_with_recovery(cut, "file_write_tool", schema)
        completed = parse_tool_call_arguments_with_recovery(cut + '"', "file_write_tool", schema)

        assert refused.safe is False
        assert refused.strategy == "truncated_mid_value"
        assert completed.safe is True
        assert completed.args == {"content": "complete body", "path": "/tmp/x"}

    def test_regex_fallback_is_marked_unsafe_without_schema(self) -> None:
        raw = 'oops "command": "rm -rf /tmp/demo" trailing'

        result = parse_tool_call_arguments_with_recovery(raw, "bash_code_execute_tool")

        assert result.degraded is True
        assert result.strategy == "regex_fallback"
        assert result.safe is False
        assert result.args["command"] == "rm -rf /tmp/demo"

    def test_parse_tool_call_args_drops_unsafe_partial_result(self) -> None:
        raw = 'oops "command": "rm -rf /tmp/demo" trailing'

        parsed = _parse_tool_call_args(raw, "bash_code_execute_tool")

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
            "bash_code_execute_tool",
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
                    "name": "bash_code_execute_tool",
                    "arguments": json.dumps({"command": 'echo "hi" &amp;&amp; ls'}),
                },
            }
        ]

        final_chunk, corrected_tool_calls, recovery_metadata = model._build_final_tool_call_chunk(
            raw_tool_calls,
            {"bash_code_execute_tool": schema},
            decode_html_entities=True,
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


class TestPythonNoneLiteralRecovery:
    """Bare Python ``None`` is repaired; the same word inside a string value is data and stays untouched."""

    @pytest.mark.parametrize(
        "content",
        [
            "def parse(raw, default=None):\n    return default if raw is None else raw\n",
            "Findings: None of the vendors reported a breach.\n",
            'He said "None" and left.',
        ],
        ids=["code", "prose", "quoted"],
    )
    def test_valid_json_is_returned_untouched(self, content: str) -> None:
        raw = json.dumps({"path": "notes.md", "content": content})

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool")

        assert result.strategy == "standard_json"
        assert result.degraded is False
        assert result.args == {"path": "notes.md", "content": content}

    def test_bare_none_is_repaired_and_string_values_are_not(self) -> None:
        raw = '{"path": "a.py", "content": "x = None", "mode": None}'

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool")

        assert result.strategy == "python_none_to_null"
        assert result.args == {"path": "a.py", "content": "x = None", "mode": None}

    def test_escaped_quote_does_not_end_the_string_early(self) -> None:
        raw = r'{"content": "say \"None\" now", "mode": None}'

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool")

        assert result.args == {"content": 'say "None" now', "mode": None}

    def test_none_inside_a_completed_string_is_preserved(self) -> None:
        raw = '{"path": "a.py", "content": "return None"'

        result = parse_tool_call_arguments_with_recovery(raw, "file_write_tool")

        assert result.safe is True
        assert "truncated_completion" in result.strategy
        assert result.args == {"path": "a.py", "content": "return None"}

    @pytest.mark.parametrize("pipeline", ["non_stream", "stream"])
    def test_tool_call_reaches_the_tool_as_the_model_sent_it(self, pipeline: str) -> None:
        content = "Findings: None of the vendors reported a breach.\n"
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "file_write_tool",
                    "arguments": json.dumps({"path": "report.md", "content": content}),
                },
            }
        ]

        if pipeline == "non_stream":
            message = convert_dict_to_message({"role": "assistant", "content": "", "tool_calls": tool_calls})
            args = message.tool_calls[0]["args"]
        else:
            payloads, metadata = recover_tool_call_payloads(tool_calls)
            args = json.loads(payloads[0]["function"]["arguments"])
            assert metadata[0]["degraded"] is False

        assert args == {"path": "report.md", "content": content}

    def test_none_scan_stays_linear_on_a_pathological_escape_tail(self) -> None:
        # 20k escaped quotes cut mid-escape: a scanner that backtracks over the escape
        # alternatives is quadratic here (seconds); a linear one finishes in milliseconds.
        payload = '{"content": "' + '\\"' * 20_000 + "\\"
        started = time.perf_counter()

        _NONE_OUTSIDE_STRINGS.findall(payload)

        assert time.perf_counter() - started < 1.0


def _raw_write_call(arguments: str) -> list[dict[str, object]]:
    return [{"id": "call_1", "type": "function", "function": {"name": "file_write_tool", "arguments": arguments}}]


class TestHasWithheldToolCalls:
    """The predicate recovery layers use to tell "the turn ended on a failed tool call" from "empty reply"."""

    @pytest.mark.parametrize(
        "additional_kwargs",
        [None, {}, {"tool_call_recovery": []}, {"tool_call_recovery": "not-a-list"}],
    )
    def test_absent_or_empty_metadata_is_not_withheld(self, additional_kwargs: dict[str, object] | None) -> None:
        assert has_withheld_tool_calls(additional_kwargs) is False

    def test_repaired_calls_are_not_withheld(self) -> None:
        items = [{"tool_call_id": "call_1", "strategy": "truncated_completion", "degraded": True, "safe": True}]

        assert has_withheld_tool_calls({"tool_call_recovery": items}) is False

    def test_malformed_items_are_ignored(self) -> None:
        items = ["safe=False", None, {"safe": None}, {}]

        assert has_withheld_tool_calls({"tool_call_recovery": items}) is False

    def test_one_unsafe_item_among_repaired_ones_is_withheld(self) -> None:
        assert has_withheld_tool_calls({"tool_call_recovery": [{"safe": True}, {"safe": False}]}) is True

    def test_detects_exactly_what_the_producer_records_for_a_cut_off_call(self) -> None:
        raw = _raw_write_call('{"path": "a.md", "content": "Revenue grew by 1')

        chunk, _, _ = build_final_tool_call_chunk(raw, stream_complete=False)

        assert chunk is not None
        assert chunk.message.tool_calls == []
        assert has_withheld_tool_calls(chunk.message.additional_kwargs) is True

    def test_does_not_flag_a_complete_call(self) -> None:
        raw = _raw_write_call('{"path": "a.md", "content": "done"}')

        chunk, _, _ = build_final_tool_call_chunk(raw, stream_complete=True)

        assert chunk is not None
        assert [call["name"] for call in chunk.message.tool_calls] == ["file_write_tool"]
        assert has_withheld_tool_calls(chunk.message.additional_kwargs) is False
