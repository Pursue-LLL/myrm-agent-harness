import json

from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import parse_tool_calls


def test_parse_deepseek_dsml_basic():
    text = """
    Thinking process...
    <｜DSML｜tool_calls>
    <｜DSML｜invoke name="search_web">
    <｜DSML｜parameter name="query" string="true">python asyncio</｜DSML｜parameter>
    <｜DSML｜parameter name="options" string="false">{"limit": 5}</｜DSML｜parameter>
    </｜DSML｜invoke>
    </｜DSML｜tool_calls>
    """

    calls = parse_tool_calls({"content": text})
    assert len(calls) == 1
    call = calls[0]
    assert call["function"]["name"] == "search_web"
    args = json.loads(call["function"]["arguments"])
    assert args["query"] == "python asyncio"
    assert args["options"]["limit"] == 5

def test_parse_deepseek_dsml_unclosed():
    # Simulate streaming chunk that is cut off
    text = """<｜DSML｜tool_calls>
    <｜DSML｜invoke name="search_web">
    <｜DSML｜parameter name="query" string="true">python asyncio</｜DSML｜parameter>
    """

    calls = parse_tool_calls({"content": text})
    assert len(calls) == 1
    call = calls[0]
    assert call["function"]["name"] == "search_web"
    args = json.loads(call["function"]["arguments"])
    assert args["query"] == "python asyncio"

def test_parse_deepseek_dsml_in_reasoning():
    reasoning = """<｜DSML｜tool_calls>
    <｜DSML｜invoke name="read_file">
    <｜DSML｜parameter name="path" string="true">/tmp/test.txt</｜DSML｜parameter>
    </｜DSML｜invoke>
    </｜DSML｜tool_calls>"""

    calls = parse_tool_calls({"reasoning_content": reasoning})
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "read_file"

def test_parse_deepseek_dsml_with_available_tools():
    text = """<｜DSML｜tool_calls>
    <｜DSML｜invoke name="search_web">
    <｜DSML｜parameter name="query" string="true">python asyncio</｜DSML｜parameter>
    </｜DSML｜invoke>
    <｜DSML｜invoke name="unknown_tool">
    <｜DSML｜parameter name="query" string="true">test</｜DSML｜parameter>
    </｜DSML｜invoke>
    </｜DSML｜tool_calls>"""

    calls = parse_tool_calls({"content": text}, available_tools=["search_web"])
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "search_web"
