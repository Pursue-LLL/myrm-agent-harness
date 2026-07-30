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
    _normalize_call_result,
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
    py_type, default = _json_schema_to_pydantic_field({"type": "integer"}, required=False)
    assert default is None


def test_field_boolean_type():
    py_type, default = _json_schema_to_pydantic_field({"type": "boolean"}, required=True)
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
# _normalize_call_result
# ---------------------------------------------------------------------------


def test_normalize_text_blocks():
    block1 = SimpleNamespace(text="hello")
    block2 = SimpleNamespace(text="world")
    result = SimpleNamespace(content=[block1, block2])
    assert _normalize_call_result(result) == "hello\nworld"


def test_normalize_binary_block():
    block = SimpleNamespace(data=b"\x00", mime_type="image/png")
    result = SimpleNamespace(content=[block])
    assert "[binary: image/png]" in _normalize_call_result(result)


def test_normalize_binary_block_no_mime():
    block = SimpleNamespace(data=b"\x00")
    result = SimpleNamespace(content=[block])
    assert "[binary: unknown]" in _normalize_call_result(result)


def test_normalize_fallback_str():
    block = SimpleNamespace(value=42)
    result = SimpleNamespace(content=[block])
    normalized = _normalize_call_result(result)
    assert "42" in normalized


def test_normalize_empty_content_list():
    result = SimpleNamespace(content=[])
    assert _normalize_call_result(result) == ""


def test_normalize_non_list_content():
    result = SimpleNamespace(content="raw string content")
    assert _normalize_call_result(result) == "raw string content"


def test_normalize_no_content_attr():
    assert "hello" in _normalize_call_result("hello")


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
    assert result == "result"
    assert captured[0] == ("search", {"query": "test"})


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
