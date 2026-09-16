import json

from myrm_agent_harness.toolkits.llms.adapters.tool_call_parcers import (
    _find_json_object_end,
    _parse_anthropic_xml_format,
    _parse_deepseek_inline_format,
    _parse_glm_xml_format,
    _parse_leaked_json_tool_calls_format,
    _parse_openai_format,
    _parse_qwen_xml_json_format,
    _parse_xml_parameter_value,
    decode_html_entities_in_args,
    parse_tool_calls,
)


def test_parse_glm_xml():
    xml = """
    <tool_call>search_web
    <arg_key>query</arg_key>
    <arg_value>test</arg_value>
    </tool_call>
    """
    res = _parse_glm_xml_format(xml)
    assert len(res) == 1
    assert res[0]["function"]["name"] == "search_web"
    args = json.loads(res[0]["function"]["arguments"])
    assert args["query"] == "test"


def test_parse_glm_xml_json_value():
    xml = """
    <tool_call>search_web
    <arg_key>options</arg_key>
    <arg_value>{"limit": 5}</arg_value>
    </tool_call>
    """
    res = _parse_glm_xml_format(xml)
    args = json.loads(res[0]["function"]["arguments"])
    assert args["options"]["limit"] == 5


def test_parse_qwen_xml_json():
    xml = '<tool_call> {"name": "search_web", "arguments": {"query": "test"}} </tool_call>'
    res = _parse_qwen_xml_json_format(xml)
    assert len(res) == 1
    assert res[0]["function"]["name"] == "search_web"


def test_parse_qwen_xml_json_string_args():
    xml = '<tool_call> {"name": "search_web", "arguments": "{\\"query\\": \\"test\\"}"} </tool_call>'
    res = _parse_qwen_xml_json_format(xml)
    assert len(res) == 1
    args = json.loads(res[0]["function"]["arguments"])
    assert args["query"] == "test"


def test_parse_anthropic_xml():
    xml = """
    <invoke name="search_web">
    <parameter name="query">test</parameter>
    <parameter name="limit" string="false">5</parameter>
    </invoke>
    """
    res = _parse_anthropic_xml_format(xml)
    assert len(res) == 1
    assert res[0]["function"]["name"] == "search_web"
    args = json.loads(res[0]["function"]["arguments"])
    assert args["query"] == "test"
    assert args["limit"] == 5


def test_parse_deepseek_inline():
    text = 'search_web {"query": "test"}'
    res = _parse_deepseek_inline_format(text, available_tools=["search_web"])
    assert len(res) == 1
    assert res[0]["function"]["name"] == "search_web"


def test_find_json_object_end():
    assert _find_json_object_end('{"a": 1} text') == 8
    assert _find_json_object_end('{"a": {"b": 2}}') == 15
    assert _find_json_object_end("not json") == -1


def test_parse_tool_calls_fallback():
    res = parse_tool_calls({"content": 'search_web {"q": 1}'}, available_tools=["search_web"])
    assert len(res) == 1

    res = parse_tool_calls(
        {"reasoning_content": "<tool_call>test\n<arg_key>q</arg_key>\n<arg_value>1</arg_value>\n</tool_call>"}
    )
    assert len(res) == 1

    res = parse_tool_calls({"content": '<invoke name="search_web"></invoke>'})
    assert len(res) == 1

    res = parse_tool_calls({"content": '<tool_call>{"name": "search"}</tool_call>'})
    assert len(res) == 1


def test_parse_openai_format_filtering():
    res = parse_tool_calls(
        {"tool_calls": [{"id": "1", "type": "function", "function": {"name": "test_tool", "arguments": "{}"}}]},
        available_tools=["other_tool"],
    )
    assert len(res) == 0


def test_parse_openai_format_no_filtering():
    res = parse_tool_calls(
        {"tool_calls": [{"id": "1", "type": "function", "function": {"name": "test_tool", "arguments": "{}"}}]},
        available_tools=["test_tool"],
    )
    assert len(res) == 1


def test_decode_html_entities():
    assert decode_html_entities_in_args("a &amp; b") == "a & b"
    assert decode_html_entities_in_args(["a &amp; b"]) == ["a & b"]
    assert decode_html_entities_in_args({"k": "a &amp; b"}) == {"k": "a & b"}


def test_parse_openai_format_missing_id_preserved():
    res = _parse_openai_format({"tool_calls": [{"type": "function", "function": {"name": "t", "arguments": "{}"}}]})
    assert len(res) == 1
    assert "id" not in res[0]


def test_parse_openai_format_duplicate_ids_deterministic():
    calls = {
        "tool_calls": [
            {"id": "call_x", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            {"id": "call_x", "type": "function", "function": {"name": "b", "arguments": "{}"}},
            {"id": "call_x", "type": "function", "function": {"name": "c", "arguments": "{}"}},
        ]
    }
    res = _parse_openai_format(calls)
    assert [tc["id"] for tc in res] == ["call_x", "call_x@2", "call_x@3"]


def test_parse_xml_parameter_value_string():
    assert _parse_xml_parameter_value("  hello  ", True) == "hello"


def test_parse_deepseek_inline_skip_branches():
    assert _parse_deepseek_inline_format('faketool {"a": 1}', ["real_tool"]) == []
    assert _parse_deepseek_inline_format('```\nreal_tool {"a": 1}\n```', ["real_tool"]) == []
    assert _parse_deepseek_inline_format('"real_tool {"a": 1}', ["real_tool"]) == []
    assert _parse_deepseek_inline_format('real_tool {"a": 1', ["real_tool"]) == []
    assert _parse_deepseek_inline_format('real_tool {"a": }', ["real_tool"]) == []
    res = _parse_deepseek_inline_format('real_tool {"a": 1}', ["real_tool"])
    assert len(res) == 1
    assert res[0]["function"]["name"] == "real_tool"
    assert res[0]["id"].startswith("call_")


def test_parse_qwen_xml_json_non_dict_args():
    res = _parse_qwen_xml_json_format('<tool_call> {"name": "qtool", "arguments": [1, 2]} </tool_call>', ["qtool"])
    assert len(res) == 1
    assert json.loads(res[0]["function"]["arguments"]) == {}


def test_parse_qwen_xml_json_list_payload_ignored():
    assert _parse_qwen_xml_json_format("<tool_call> [1, 2] </tool_call>", ["qtool"]) == []


def test_find_json_object_end_escape_and_unbalanced():
    assert _find_json_object_end('{"a": "x\\"y"}') == 13
    assert _find_json_object_end('{"a": 1') == -1
    assert _find_json_object_end("nope") == -1


def test_parse_leaked_json_whole_object():
    content = '{"tool_calls": [{"name": "file_read_tool", "arguments": {"path": "a"}}, {"function": {"name": "grep_tool", "arguments": "{}"}}]}'
    res = _parse_leaked_json_tool_calls_format(content, ["file_read_tool", "grep_tool"])
    assert [tc["function"]["name"] for tc in res] == ["file_read_tool", "grep_tool"]
    assert json.loads(res[0]["function"]["arguments"]) == {"path": "a"}
    assert res[1]["function"]["arguments"] == "{}"


def test_parse_leaked_json_fence_filter_dedup_id():
    content = '```json\n{"tool_calls": [{"id": "keep-me", "name": "t", "arguments": {}}, {"name": "t", "arguments": {}}, {"name": "nope", "arguments": {}}]}\n```'
    res = _parse_leaked_json_tool_calls_format(content, ["t"])
    assert len(res) == 1
    assert res[0]["id"] == "keep-me"


def test_parse_leaked_json_single_dict_and_null_args():
    res = _parse_leaked_json_tool_calls_format('{"name": "t", "arguments": null}', ["t"])
    assert len(res) == 1
    assert json.loads(res[0]["function"]["arguments"]) == {}


def test_parse_leaked_json_skips_invalid():
    assert _parse_leaked_json_tool_calls_format("xx ```json {oops} ``` name", ["t"]) == []
    assert _parse_leaked_json_tool_calls_format('{"tool_calls": [42]}', ["t"]) == []
    assert _parse_leaked_json_tool_calls_format('{"tool_calls": [{"arguments": {}}]}', ["t"]) == []
    assert _parse_leaked_json_tool_calls_format("nothing to parse here", ["t"]) == []


def test_parse_tool_calls_reaches_leaked_json():
    content = '{"tool_calls": [{"name": "file_read_tool", "arguments": {"path": "a"}}]}'
    res = parse_tool_calls({"content": content}, available_tools=["file_read_tool"])
    assert len(res) == 1
    assert res[0]["function"]["name"] == "file_read_tool"
