"""MCP tool schema → LangChain BaseTool converter.

Converts MCP ``Tool`` objects (from ``client.list_tools()``) into LangChain
``StructuredTool`` instances whose ``ainvoke`` calls the provided
session/client's ``call_tool`` method.

The coroutine returns the raw ``mcp.types.CallToolResult`` from ``call_tool``
unchanged — result normalization (is_error detection, content-block coercion,
multimodal passthrough, structured_content merging, ext-apps metadata) is
owned by ``MCPAgent._normalize_mcp_result`` / ``_emit_mcp_app_event`` in the
single post-processing chain (``process_session_tools``), so rich output is
never flattened here.

[INPUT]
- mcp.types::Tool (POS: MCP tool schema type)
- mcp.client.client::Client (POS: MCP SDK 2.x high-level client)

[OUTPUT]
- convert_mcp_tools: MCP Tool list → LangChain StructuredTool list

[POS]
MCP-to-LangChain tool schema bridge using ``mcp`` SDK 2.x natively.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, create_model

from myrm_agent_harness.toolkits.mcp.schema_utils import (
    flatten_json_schema,
    flatten_top_level_composite,
    prepare_mcp_call_arguments,
)

logger = logging.getLogger(__name__)

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _primary_json_type(schema: dict[str, Any]) -> str:
    """Resolve the primary JSON Schema type for a property.

    FastMCP emits nullable fields as ``anyOf: [{...}, {"type": "null"}]`` and
    some servers use array ``type`` (``["object", "null"]``); neither form has
    a top-level string ``type``, so a naive lookup would degrade the field to
    ``str``. Collapse to the first non-null variant for a concrete Pydantic
    annotation. Unknown types fall back to ``string`` (permissive, never
    blocks a call).
    """
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type
    if isinstance(raw_type, list):
        for entry in raw_type:
            if isinstance(entry, str) and entry != "null":
                return entry
        return "string"
    for union_key in ("anyOf", "oneOf"):
        variants = schema.get(union_key)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            variant_type = variant.get("type")
            if isinstance(variant_type, str) and variant_type != "null":
                return variant_type
            if isinstance(variant_type, list):
                for entry in variant_type:
                    if isinstance(entry, str) and entry != "null":
                        return entry
    return "string"


def _json_schema_to_pydantic_field(
    schema: dict[str, Any],
    required: bool,
) -> tuple[type, Any]:
    """Map a single JSON Schema property to a Pydantic (type, default) tuple."""
    py_type: type = _JSON_TYPE_MAP.get(_primary_json_type(schema), str)
    if not required:
        return (py_type | None, None)  # type: ignore[return-value]
    return (py_type, ...)


def _build_args_model(tool_name: str, input_schema: dict[str, Any]) -> type[BaseModel]:
    """Dynamically create a Pydantic model from an MCP tool's inputSchema."""
    properties: dict[str, Any] = input_schema.get("properties", {})
    required_set: set[str] = set(input_schema.get("required", []))

    if not properties:
        return create_model(f"{tool_name}_Args")  # type: ignore[call-overload]

    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        fields[prop_name] = _json_schema_to_pydantic_field(
            prop_schema,
            prop_name in required_set,
        )
    return create_model(f"{tool_name}_Args", **fields)  # type: ignore[call-overload]


def convert_mcp_tools(
    tools: list[Any],
    call_tool_fn: Callable[..., Awaitable[object]],
    server_name: str = "",
) -> list[StructuredTool]:
    """Convert MCP Tool objects to LangChain StructuredTool instances.

    Args:
        tools: List of ``mcp.types.Tool`` objects from ``client.list_tools()``.
        call_tool_fn: Async callable ``(name, arguments) -> CallToolResult``.
            Typically ``client.call_tool``.
        server_name: Server name for logging.

    Returns:
        List of LangChain ``StructuredTool`` instances.  Each tool's coroutine
        resolves ``CallToolResult`` from ``call_tool_fn`` unchanged — content
        normalization is deferred to ``MCPAgent`` (see module docstring).
    """
    result: list[StructuredTool] = []
    for tool in tools:
        tool_name: str = tool.name
        description: str = getattr(tool, "description", "") or ""
        input_schema: dict[str, Any] = getattr(tool, "input_schema", {}) or {}
        if isinstance(input_schema, str):
            input_schema = json.loads(input_schema)
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}

        # Resolve $ref/$defs inline before building the Pydantic args model:
        # FastMCP emits nested/optional models as $defs + $ref (no `type`),
        # which would otherwise degrade to `str` fields and reject valid
        # dict arguments at validation time. Deterministic and idempotent —
        # a schema without $ref passes through unchanged.
        ref_resolved = flatten_json_schema(input_schema)
        composite_flattened = flatten_top_level_composite(ref_resolved)

        # Flattening may fold mutual-exclusivity hints into the schema-level
        # description (e.g. oneOf alternatives).  Pydantic args models drop
        # top-level schema descriptions, so surface the hint on the tool
        # description that the LLM actually sees — only when composite
        # flattening actually happened (returns the same object otherwise).
        if composite_flattened is not ref_resolved:
            schema_hint = composite_flattened.get("description")
            if schema_hint and schema_hint not in description:
                description = f"{description}\n{schema_hint}".strip()
        input_schema = composite_flattened

        try:
            args_model = _build_args_model(tool_name, input_schema)
        except Exception:
            logger.warning(
                "MCP server '%s': failed to build args model for tool '%s', using empty schema",
                server_name,
                tool_name,
                exc_info=True,
            )
            args_model = create_model(f"{tool_name}_Args")  # type: ignore[call-overload]

        captured_name = tool_name
        captured_schema = input_schema

        def _make_invoker(
            invoke_name: str = captured_name,
            invoke_schema: dict[str, Any] = captured_schema,
        ) -> Callable[..., Awaitable[object]]:
            async def _invoke(**kwargs: object) -> object:
                # Keep the coroutine signature keyword-only: positional names like
                # `name` / `schema` would shadow same-named MCP tool arguments and
                # silently drop them from the dispatched payload.  The per-iteration
                # name/schema are bound via default-argument capture (evaluated at
                # `_make_invoker` call time), which is immune to loop-variable late
                # binding — each tool keeps its own schema.
                call_args = prepare_mcp_call_arguments(kwargs, invoke_schema)
                return await call_tool_fn(invoke_name, call_args)

            return _invoke

        lc_tool = StructuredTool(
            name=tool_name,
            description=description,
            args_schema=args_model,
            coroutine=_make_invoker(),
            response_format="content",
        )
        result.append(lc_tool)

    if server_name:
        logger.debug(
            "MCP server '%s': converted %d tools to LangChain format",
            server_name,
            len(result),
        )
    return result
