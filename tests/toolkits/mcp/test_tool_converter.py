"""Unit tests for tool_converter.py — MCP tool schema → LangChain BaseTool converter.

The converter passes the normalized JSON Schema dict through verbatim as
``args_schema`` (no Pydantic model), so assertions inspect the dict schema
directly and verify that LLM-facing semantics (description/enum/min-max/
nested properties) survive end-to-end via ``convert_to_openai_tool``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from myrm_agent_harness.toolkits.mcp.tool_converter import convert_mcp_tools


def _make_mcp_tool(
    name: str,
    description: str = "test tool",
    input_schema: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=description,
        input_schema=input_schema or {"type": "object", "properties": {}},
    )


def _props(tool) -> dict[str, Any]:
    return tool.args_schema.get("properties", {})


# ---------------------------------------------------------------------------
# convert_mcp_tools — schema passthrough (dict, no Pydantic model)
# ---------------------------------------------------------------------------


def test_convert_basic_tool():
    async def fake_call(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    tools = convert_mcp_tools([_make_mcp_tool("ping")], fake_call, server_name="test")
    assert len(tools) == 1
    assert tools[0].name == "ping"
    assert tools[0].description == "test tool"
    assert isinstance(tools[0].args_schema, dict)


def test_convert_preserves_order():
    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    mcp_tools = [_make_mcp_tool(f"tool_{i}") for i in range(5)]
    lc_tools = convert_mcp_tools(mcp_tools, noop)
    assert [t.name for t in lc_tools] == [f"tool_{i}" for i in range(5)]


def test_convert_tool_with_args_schema():
    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    }
    tools = convert_mcp_tools([_make_mcp_tool("search", input_schema=schema)], noop)
    assert "q" in _props(tools[0])


def test_convert_tool_preserves_field_semantics():
    """description/enum/min-max must survive verbatim in the LLM-facing schema."""

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "出发日期"},
            "trainType": {"type": "string", "enum": ["G", "D", "K"]},
            "tickets": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "required": ["date"],
    }
    tools = convert_mcp_tools([_make_mcp_tool("query", input_schema=schema)], noop)
    props = _props(tools[0])
    assert props["date"]["description"] == "出发日期"
    assert props["trainType"]["enum"] == ["G", "D", "K"]
    assert props["tickets"]["minimum"] == 1
    assert props["tickets"]["maximum"] == 5


def test_convert_tool_with_top_level_oneof_flattens_params():
    """kimi-cu style oneOf input schemas keep every parameter, all optional."""

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    schema: dict[str, Any] = {
        "type": "object",
        "oneOf": [
            {"type": "object", "properties": {"index": {"type": "integer"}}},
            {
                "type": "object",
                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
            },
        ],
    }
    tools = convert_mcp_tools([_make_mcp_tool("click", input_schema=schema)], noop)
    assert set(_props(tools[0])) == {"index", "x", "y"}
    assert "required" not in tools[0].args_schema


async def test_convert_tool_oneof_branch_invocation_dispatches():
    """An index-branch call must reach the MCP server with the value intact."""
    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_call(name: str, args: dict[str, Any]) -> SimpleNamespace:
        captured.append((name, args))
        return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    schema: dict[str, Any] = {
        "type": "object",
        "oneOf": [
            {"type": "object", "properties": {"index": {"type": "integer"}}},
            {
                "type": "object",
                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
            },
        ],
    }
    tools = convert_mcp_tools([_make_mcp_tool("click", input_schema=schema)], capture_call)
    await tools[0].ainvoke({"index": 3})
    assert captured[0] == ("click", {"index": 3})


def test_convert_tool_surfaces_exclusivity_hint_on_schema_description():
    """oneOf flattening hints must be visible in the LLM-facing schema description."""

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    schema: dict[str, Any] = {
        "type": "object",
        "oneOf": [
            {"type": "object", "properties": {"index": {"type": "integer"}}},
            {
                "type": "object",
                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
            },
        ],
    }
    tools = convert_mcp_tools([_make_mcp_tool("click", input_schema=schema)], noop)
    hint = tools[0].args_schema.get("description", "")
    assert "mutually exclusive" in hint
    assert "(x, y)" in hint


async def test_convert_multi_tool_closure_captures_own_name_and_schema():
    """Each tool's coroutine must dispatch with its own name/schema.

    The coroutine captures per-tool name/schema at creation time; a shared
    late-bound loop variable would leak the last tool's schema into every
    dispatch (observed regression after switching _invoke to **kwargs).
    """
    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_call(name: str, args: dict[str, Any]) -> SimpleNamespace:
        captured.append((name, args))
        return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    echo_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    add_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }
    tools = convert_mcp_tools(
        [
            _make_mcp_tool("echo", input_schema=echo_schema),
            _make_mcp_tool("add", input_schema=add_schema),
        ],
        capture_call,
    )
    await tools[0].ainvoke({"text": "hi"})
    await tools[1].ainvoke({"a": 1, "b": 2})
    assert captured == [
        ("echo", {"text": "hi"}),
        ("add", {"a": 1, "b": 2}),
    ]


async def test_convert_tool_invocation():
    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_call(name: str, args: dict[str, Any]) -> SimpleNamespace:
        captured.append((name, args))
        return SimpleNamespace(content=[SimpleNamespace(text="result")])

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    tools = convert_mcp_tools(
        [_make_mcp_tool("search", input_schema=schema)],
        capture_call,
    )
    result = await tools[0].ainvoke({"query": "test"})
    # _invoke passes the raw CallToolResult through unchanged; content
    # normalization happens later in result_processing.normalize_mcp_result.
    assert result.content[0].text == "result"
    assert captured[0] == ("search", {"query": "test"})


async def test_convert_strips_null_optional_fields_before_call_tool():
    """12306-style strict schemas reject explicit null on optional typed fields."""
    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_call(name: str, args: dict[str, Any]) -> SimpleNamespace:
        captured.append((name, args))
        return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "fromStation": {"type": "string"},
            "toStation": {"type": "string"},
            "trainFilterFlags": {"type": "string", "default": ""},
            "earliestStartTime": {"type": "number", "default": 0},
        },
        "required": ["date", "fromStation", "toStation"],
        "additionalProperties": False,
    }
    tools = convert_mcp_tools(
        [_make_mcp_tool("get-tickets", input_schema=schema)],
        capture_call,
    )
    await tools[0].ainvoke(
        {
            "date": "2026-08-06",
            "fromStation": "BJP",
            "toStation": "SHH",
        }
    )
    assert captured[0][0] == "get-tickets"
    assert captured[0][1] == {
        "date": "2026-08-06",
        "fromStation": "BJP",
        "toStation": "SHH",
    }
    assert "trainFilterFlags" not in captured[0][1]
    assert "earliestStartTime" not in captured[0][1]


async def test_convert_tool_with_nested_ref_flattens_params_and_dispatches():
    """MCPServer nested-model tools ($defs/$ref) keep nested dict args intact."""

    class Address(BaseModel):
        street: str
        city: str

    class User(BaseModel):
        name: str
        age: int
        address: Address

    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_call(name: str, args: dict[str, Any]) -> SimpleNamespace:
        captured.append((name, args))
        return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    tools = convert_mcp_tools(
        [_make_mcp_tool("create_user", input_schema=User.model_json_schema())],
        capture_call,
    )
    address_prop = _props(tools[0])["address"]
    assert address_prop["type"] == "object"
    assert "street" in address_prop.get("properties", {})

    await tools[0].ainvoke(
        {
            "name": "Alice",
            "age": 30,
            "address": {"street": "1 Main St", "city": "NY"},
        }
    )
    assert captured[0] == (
        "create_user",
        {
            "name": "Alice",
            "age": 30,
            "address": {"street": "1 Main St", "city": "NY"},
        },
    )


def test_convert_tool_with_optional_nested_ref_preserves_object():
    """MCPServer optional nested fields (anyOf[$ref, null]) stay object-typed."""

    class Address(BaseModel):
        street: str

    class User(BaseModel):
        name: str
        address: Address | None = None

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    tools = convert_mcp_tools(
        [_make_mcp_tool("create_user", input_schema=User.model_json_schema())],
        noop,
    )
    address_prop = _props(tools[0])["address"]
    # $ref is inlined but the nullable union shape is preserved verbatim
    # (the LLM-facing normalizer collapses single-non-null anyOf branches
    # at bind time). The object branch must carry its nested properties.
    non_null_branches = [b for b in address_prop.get("anyOf", []) if isinstance(b, dict) and b.get("type") != "null"]
    assert non_null_branches
    assert non_null_branches[0]["type"] == "object"
    assert "street" in non_null_branches[0].get("properties", {})


def test_convert_tool_with_ref_branch_in_union_infers_type():
    """$ref inside a union must resolve through flatten before LLM exposure."""

    class Payload(BaseModel):
        kind: str

    schema: dict[str, Any] = {
        "type": "object",
        "$defs": {
            "Payload": {
                "type": "object",
                "properties": {"kind": {"type": "string"}},
            }
        },
        "properties": {
            "payload": {
                "anyOf": [{"$ref": "#/$defs/Payload"}, {"type": "null"}],
            },
        },
        "required": ["payload"],
    }

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    tools = convert_mcp_tools([_make_mcp_tool("emit", input_schema=schema)], noop)
    payload_prop = _props(tools[0])["payload"]
    # $ref resolved inline inside the union; the object branch must survive.
    non_null_branches = [b for b in payload_prop.get("anyOf", []) if isinstance(b, dict) and b.get("type") != "null"]
    assert non_null_branches
    assert non_null_branches[0]["type"] == "object"


def test_convert_tool_with_type_array_property():
    """type: [object, null] on a property must stay object-typed."""

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "config": {"type": ["object", "null"]},
        },
        "required": ["config"],
    }
    tools = convert_mcp_tools([_make_mcp_tool("apply", input_schema=schema)], noop)
    config_prop = _props(tools[0])["config"]
    # `type: [object, null]` survives verbatim; the object branch must be present.
    assert "object" in config_prop["type"]


def test_convert_string_input_schema():
    """input_schema as JSON string should be parsed."""

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    tool = SimpleNamespace(
        name="json_str",
        description="test",
        input_schema='{"type": "object", "properties": {"x": {"type": "integer"}}}',
    )
    lc_tools = convert_mcp_tools([tool], noop)
    assert "x" in _props(lc_tools[0])


def test_convert_non_dict_input_schema():
    """Non-dict/non-string input_schema should fall back to empty."""

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    tool = SimpleNamespace(name="bad_schema", description="test", input_schema=42)
    lc_tools = convert_mcp_tools([tool], noop)
    assert len(lc_tools) == 1


def test_convert_missing_description():
    """Missing description should default to empty string."""

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    tool = SimpleNamespace(name="no_desc", input_schema={})
    lc_tools = convert_mcp_tools([tool], noop)
    assert lc_tools[0].description == ""


def test_convert_none_description():
    """None description should default to empty string."""

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    tool = SimpleNamespace(name="none_desc", description=None, input_schema={})
    lc_tools = convert_mcp_tools([tool], noop)
    assert lc_tools[0].description == ""


# ---------------------------------------------------------------------------
# LLM-facing schema semantics (via convert_to_openai_tool)
# ---------------------------------------------------------------------------


def test_llm_visible_schema_preserves_full_semantics():
    """The schema the LLM actually sees must keep description/enum/min-max/nesting."""

    async def noop(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[])

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "出发日期，格式 YYYY-MM-DD"},
            "trainType": {
                "type": "string",
                "enum": ["G", "D", "K"],
                "description": "列车类型",
            },
            "tickets": {"type": "integer", "minimum": 1, "maximum": 5},
            "address": {
                "type": "object",
                "properties": {
                    "street": {"type": "string", "description": "街道"},
                    "city": {"type": "string", "description": "城市"},
                },
                "required": ["street"],
            },
        },
        "required": ["date", "trainType"],
    }
    tools = convert_mcp_tools([_make_mcp_tool("query", input_schema=schema)], noop)
    openai_tool = convert_to_openai_tool(tools[0])
    params = openai_tool["function"]["parameters"]
    props = params["properties"]

    assert props["date"]["description"] == "出发日期，格式 YYYY-MM-DD"
    assert props["trainType"]["enum"] == ["G", "D", "K"]
    assert props["tickets"]["minimum"] == 1
    assert props["tickets"]["maximum"] == 5
    assert "street" in props["address"]["properties"]
    assert props["address"]["required"] == ["street"]
    assert params["required"] == ["date", "trainType"]


# ---------------------------------------------------------------------------
# Real MCP SDK objects — snake_case fields must be read correctly
# ---------------------------------------------------------------------------


def test_convert_real_sdk_tool_input_schema():
    """``mcp.types.Tool`` exposes ``input_schema`` (snake_case); the converter
    must read it or every real server's args schema silently becomes empty."""
    from mcp.types import Tool

    async def fake_call(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    sdk_tool = Tool(
        name="search",
        description="search tool",
        input_schema=schema,
    )
    tools = convert_mcp_tools([sdk_tool], fake_call)
    assert len(tools) == 1
    assert tools[0].name == "search"
    assert tools[0].args_schema["properties"]["query"]["type"] == "string"
    assert tools[0].args_schema["required"] == ["query"]
