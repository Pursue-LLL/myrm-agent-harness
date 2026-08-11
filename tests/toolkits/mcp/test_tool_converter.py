"""Unit tests for tool_converter.py — MCP tool schema → LangChain BaseTool converter."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from myrm_agent_harness.toolkits.mcp.tool_converter import (
    _build_args_model,
    _json_schema_to_pydantic_field,
    convert_mcp_tools,
)

# ---------------------------------------------------------------------------
# _json_schema_to_pydantic_field
# ---------------------------------------------------------------------------


def test_field_required_string():
    py_type, default = _json_schema_to_pydantic_field({"type": "string"}, required=True)
    assert py_type is str
    assert default is ...


def test_field_optional_integer():
    _py_type, default = _json_schema_to_pydantic_field(
        {"type": "integer"}, required=False
    )
    assert default is None


def test_field_boolean_type():
    py_type, _default = _json_schema_to_pydantic_field(
        {"type": "boolean"}, required=True
    )
    assert py_type is bool


def test_field_array_type():
    py_type, _ = _json_schema_to_pydantic_field({"type": "array"}, required=True)
    assert py_type is list


def test_field_object_type():
    py_type, _ = _json_schema_to_pydantic_field({"type": "object"}, required=True)
    assert py_type is dict


def test_field_unknown_type_defaults_to_str():
    py_type, _ = _json_schema_to_pydantic_field({"type": "custom_thing"}, required=True)
    assert py_type is str


def test_field_missing_type_defaults_to_str():
    py_type, _ = _json_schema_to_pydantic_field({}, required=True)
    assert py_type is str


def test_field_nullable_object_union_infers_dict():
    """anyOf(object, null) — FastMCP optional nested field — must be dict, not str."""
    py_type, default = _json_schema_to_pydantic_field(
        {"anyOf": [{"type": "object"}, {"type": "null"}], "default": None},
        required=False,
    )
    assert py_type == dict | None
    assert default is None


def test_field_nullable_object_union_required_infers_dict():
    py_type, default = _json_schema_to_pydantic_field(
        {"anyOf": [{"type": "object"}, {"type": "null"}]},
        required=True,
    )
    assert py_type is dict
    assert default is ...


def test_field_type_array_object_null_infers_dict():
    """type: [object, null] collapses to the first non-null variant."""
    py_type, _ = _json_schema_to_pydantic_field(
        {"type": ["object", "null"]},
        required=True,
    )
    assert py_type is dict


def test_field_union_prefers_first_non_null_variant():
    py_type, _ = _json_schema_to_pydantic_field(
        {"anyOf": [{"type": "array"}, {"type": "null"}]},
        required=True,
    )
    assert py_type is list


def test_field_all_null_union_falls_back_to_str():
    py_type, _ = _json_schema_to_pydantic_field(
        {"anyOf": [{"type": "null"}]},
        required=True,
    )
    assert py_type is str


# ---------------------------------------------------------------------------
# _build_args_model
# ---------------------------------------------------------------------------


def test_build_empty_schema():
    model = _build_args_model("empty_tool", {"type": "object", "properties": {}})
    assert issubclass(model, BaseModel)
    assert model.__name__ == "empty_tool_Args"


def test_build_no_properties_key():
    model = _build_args_model("bare", {})
    assert issubclass(model, BaseModel)


def test_build_with_required_and_optional():
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    }
    model = _build_args_model("search", schema)
    fields = model.model_fields
    assert "query" in fields
    assert "limit" in fields
    assert fields["query"].is_required()
    assert not fields["limit"].is_required()


# ---------------------------------------------------------------------------
# convert_mcp_tools
# ---------------------------------------------------------------------------


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


def test_convert_basic_tool():
    async def fake_call(name: str, args: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(content=[SimpleNamespace(text="ok")])

    tools = convert_mcp_tools([_make_mcp_tool("ping")], fake_call, server_name="test")
    assert len(tools) == 1
    assert tools[0].name == "ping"
    assert tools[0].description == "test tool"


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
    assert "q" in tools[0].args_schema.model_fields


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
    fields = tools[0].args_schema.model_fields
    assert set(fields) == {"index", "x", "y"}
    assert not any(f.is_required() for f in fields.values())


def test_convert_tool_oneof_branch_invocation_dispatches():
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
    asyncio.get_event_loop().run_until_complete(tools[0].ainvoke({"index": 3}))
    assert captured[0] == ("click", {"index": 3})


def test_convert_tool_surfaces_exclusivity_hint_on_description():
    """oneOf flattening hints must be visible in the LLM-facing description."""

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
    assert "mutually exclusive" in tools[0].description
    assert "(x, y)" in tools[0].description


def test_convert_multi_tool_closure_captures_own_name_and_schema():
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
    asyncio.get_event_loop().run_until_complete(tools[0].ainvoke({"text": "hi"}))
    asyncio.get_event_loop().run_until_complete(
        tools[1].ainvoke({"a": 1, "b": 2})
    )
    assert captured == [
        ("echo", {"text": "hi"}),
        ("add", {"a": 1, "b": 2}),
    ]


def test_convert_tool_invocation():
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
    result = asyncio.get_event_loop().run_until_complete(
        tools[0].ainvoke({"query": "test"})
    )
    # _invoke passes the raw CallToolResult through unchanged; content
    # normalization happens later in MCPAgent._normalize_mcp_result.
    assert result.content[0].text == "result"
    assert captured[0] == ("search", {"query": "test"})


def test_convert_strips_null_optional_fields_before_call_tool():
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
    asyncio.get_event_loop().run_until_complete(
        tools[0].ainvoke(
            {
                "date": "2026-08-06",
                "fromStation": "BJP",
                "toStation": "SHH",
            }
        )
    )
    assert captured[0][0] == "get-tickets"
    assert captured[0][1] == {
        "date": "2026-08-06",
        "fromStation": "BJP",
        "toStation": "SHH",
    }
    assert "trainFilterFlags" not in captured[0][1]
    assert "earliestStartTime" not in captured[0][1]


def test_convert_tool_with_nested_ref_flattens_params_and_dispatches():
    """FastMCP nested-model tools ($defs/$ref) keep dict args and dispatch intact."""

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
    fields = tools[0].args_schema.model_fields
    assert "address" in fields
    assert fields["address"].annotation is dict

    asyncio.get_event_loop().run_until_complete(
        tools[0].ainvoke(
            {
                "name": "Alice",
                "age": 30,
                "address": {"street": "1 Main St", "city": "NY"},
            }
        )
    )
    assert captured[0] == (
        "create_user",
        {
            "name": "Alice",
            "age": 30,
            "address": {"street": "1 Main St", "city": "NY"},
        },
    )


def test_convert_tool_with_optional_nested_ref_infers_optional_dict():
    """FastMCP optional nested fields (anyOf[$ref, null]) infer dict | None."""

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
    field_ann = tools[0].args_schema.model_fields["address"].annotation
    assert field_ann == dict | None


def test_convert_tool_with_ref_branch_in_union_infers_type():
    """$ref inside a union must resolve through flatten before type inference."""

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
    assert tools[0].args_schema.model_fields["payload"].annotation is dict


def test_convert_tool_with_type_array_property():
    """type: [object, null] on a property must not degrade the field to str."""

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
    assert tools[0].args_schema.model_fields["config"].annotation is dict


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
    assert "x" in lc_tools[0].args_schema.model_fields


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


@pytest.mark.parametrize(
    "json_type,expected_python_type",
    [
        ("string", str),
        ("integer", int),
        ("number", float),
        ("boolean", bool),
        ("array", list),
        ("object", dict),
    ],
)
def test_field_type_mapping_parametrized(json_type: str, expected_python_type: type):
    py_type, _ = _json_schema_to_pydantic_field({"type": json_type}, required=True)
    assert py_type is expected_python_type
