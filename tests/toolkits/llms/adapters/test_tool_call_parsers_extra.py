import json

from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import (
    _find_json_object_end,
    _parse_anthropic_xml_format,
    _parse_deepseek_inline_format,
    _parse_glm_xml_format,
    _parse_qwen_xml_json_format,
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
    assert _find_json_object_end('not json') == -1

def test_parse_tool_calls_fallback():
    res = parse_tool_calls({"content": "search_web {\"q\": 1}"}, available_tools=["search_web"])
    assert len(res) == 1

    res = parse_tool_calls({"reasoning_content": "<tool_call>test\n<arg_key>q</arg_key>\n<arg_value>1</arg_value>\n</tool_call>"})
    assert len(res) == 1

    res = parse_tool_calls({"content": "<invoke name=\"search_web\"></invoke>"})
    assert len(res) == 1

    res = parse_tool_calls({"content": "<tool_call>{\"name\": \"search\"}</tool_call>"})
    assert len(res) == 1

def test_parse_openai_format_filtering():
    res = parse_tool_calls(
        {"tool_calls": [{"id": "1", "type": "function", "function": {"name": "test_tool", "arguments": "{}"}}]},
        available_tools=["other_tool"]
    )
    assert len(res) == 0

def test_parse_openai_format_no_filtering():
    res = parse_tool_calls(
        {"tool_calls": [{"id": "1", "type": "function", "function": {"name": "test_tool", "arguments": "{}"}}]},
        available_tools=["test_tool"]
    )
    assert len(res) == 1

def test_decode_html_entities():
    assert decode_html_entities_in_args("a &amp; b") == "a & b"
    assert decode_html_entities_in_args(["a &amp; b"]) == ["a & b"]
    assert decode_html_entities_in_args({"k": "a &amp; b"}) == {"k": "a & b"}
