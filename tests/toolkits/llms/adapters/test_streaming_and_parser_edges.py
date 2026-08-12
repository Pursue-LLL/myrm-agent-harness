"""Edge-path coverage for streaming utilities and tool-call parser guards.

Complements the happy-path suites by exercising malformed-chunk protection,
usage normalization fallbacks, and parser skip/guard branches.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.adapters.streaming import (
    aggregate_tool_call_chunk,
    build_tool_call_chunks,
    normalize_usage,
    safe_get,
)
from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import (
    _parse_anthropic_xml_format,
    _parse_glm_xml_format,
    _parse_qwen_xml_json_format,
)


class TestSafeGet:
    def test_none_returns_default(self) -> None:
        assert safe_get(None, "key", "fallback") == "fallback"

    def test_dict_and_object(self) -> None:
        assert safe_get({"a": 1}, "a") == 1
        assert safe_get({"a": 1}, "b", 9) == 9

        class _Obj:
            a = 2

        assert safe_get(_Obj(), "a") == 2
        assert safe_get(_Obj(), "b", 9) == 9


class TestBuildToolCallChunks:
    def test_non_list_returns_empty(self) -> None:
        assert build_tool_call_chunks({"function": {}}) == []

    def test_skips_non_dict_entries_and_missing_function(self) -> None:
        chunks = build_tool_call_chunks([123, {"function": "not-a-dict"}, None])
        assert chunks == []

    def test_builds_chunk_with_id_mapping(self) -> None:
        id_map: dict[str, str] = {}
        chunks = build_tool_call_chunks(
            [
                {
                    "id": "c1",
                    "function": {"name": "f", "arguments": '{"a":1}'},
                    "index": 0,
                }
            ],
            tool_call_id_map=id_map,
        )
        assert len(chunks) == 1
        assert chunks[0]["id"] == id_map["c1"]
        assert chunks[0]["id"] != "c1"
        assert chunks[0]["name"] == "f"


class TestAggregateToolCallChunk:
    def test_dict_args_serialized(self) -> None:
        aggregated: list[dict[str, object]] = [{"function": {"name": "", "arguments": ""}, "id": ""}]
        aggregate_tool_call_chunk(
            {"index": 0, "name": "f", "args": {"a": 1}, "id": "c1"},
            aggregated,
        )
        assert aggregated[0]["function"]["arguments"] == '{"a": 1}'
        assert aggregated[0]["id"] == "c1"

    def test_unexpected_args_type_warns(self) -> None:
        aggregated: list[dict[str, object]] = [{"function": {"name": "", "arguments": ""}, "id": ""}]
        aggregate_tool_call_chunk({"index": 0, "args": 42}, aggregated)
        assert aggregated[0]["function"]["arguments"] == ""

    def test_missing_index_uses_zero(self) -> None:
        aggregated: list[dict[str, object]] = []
        aggregate_tool_call_chunk({"name": "f", "args": "x"}, aggregated)
        assert aggregated[0]["function"]["name"] == "f"


class TestNormalizeUsage:
    def test_dict_passthrough(self) -> None:
        assert normalize_usage({"total_tokens": 5}) == {"total_tokens": 5}

    def test_duck_typed_object(self) -> None:
        class _Usage:
            prompt_tokens = 1
            completion_tokens = 2
            total_tokens = 3

        assert normalize_usage(_Usage()) == {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
        }


class TestGlmXmlGuards:
    def test_empty_tool_name_skipped(self) -> None:
        assert _parse_glm_xml_format("<tool_call></tool_call>") == []


class TestQwenXmlJsonGuards:
    def test_json_decode_failure_repaired(self) -> None:
        result = _parse_qwen_xml_json_format(
            '<tool_call> {"name": "echo", "arguments": {"text": ""hi""}} </tool_call>'
        )
        assert result and result[0]["function"]["name"] == "echo"

    def test_function_wrapper_and_missing_name(self) -> None:
        result = _parse_qwen_xml_json_format(
            '<tool_call> {"function": {"name": "f", "arguments": {"a": 1}}} </tool_call>'
        )
        assert result and result[0]["function"]["name"] == "f"
        assert _parse_qwen_xml_json_format('<tool_call> {"arguments": {}} </tool_call>') == []

    def test_available_tools_filter(self) -> None:
        result = _parse_qwen_xml_json_format(
            '<tool_call> {"name": "f"} </tool_call>', available_tools=["other"]
        )
        assert result == []

    def test_string_and_non_dict_args(self) -> None:
        result = _parse_qwen_xml_json_format(
            '<tool_call> {"name": "f", "arguments": "{\\"a\\": 1}"} </tool_call>'
        )
        assert result and result[0]["function"]["arguments"]

    def test_fully_malformed_skipped(self) -> None:
        assert _parse_qwen_xml_json_format('<tool_call> }broken{ </tool_call>') == []


class TestAnthropicXmlGuards:
    def test_available_tools_filter(self) -> None:
        result = _parse_anthropic_xml_format(
            '<invoke name="f"><parameter name="a">1</parameter></invoke>',
            available_tools=["other"],
        )
        assert result == []

    def test_code_block_skip(self) -> None:
        content = '```xml\n<invoke name="f"><parameter name="a">1</parameter></invoke>\n```'
        result = _parse_anthropic_xml_format(content, available_tools=["f"])
        assert result == []

    def test_antml_prefix_invoke(self) -> None:
        result = _parse_anthropic_xml_format(
            '<antml:invoke name="f"><antml:parameter name="a">1</antml:parameter></antml:invoke>',
            available_tools=["f"],
        )
        assert result and result[0]["function"]["name"] == "f"


class TestQwenXmlGuards:
    def test_empty_content(self) -> None:
        assert _parse_qwen_xml_json_format("") == []
