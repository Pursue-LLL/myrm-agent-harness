"""MCP tool schema → LangChain BaseTool converter.

Converts MCP ``Tool`` objects (from ``client.list_tools()``) into LangChain
``StructuredTool`` instances whose ``ainvoke`` calls the provided
session/client's ``call_tool`` method.

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

from myrm_agent_harness.toolkits.mcp.schema_utils import prepare_mcp_call_arguments

logger = logging.getLogger(__name__)


def _json_schema_to_pydantic_field(
    schema: dict[str, Any],
    required: bool,
) -> tuple[type, Any]:
    """Map a single JSON Schema property to a Pydantic (type, default) tuple."""
    json_type = schema.get("type", "string")
    type_map: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    py_type: type = type_map.get(json_type, str)
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


def _normalize_call_result(result: object) -> str:
    """Extract text content from a ``CallToolResult``."""
    if hasattr(result, "content"):
        content = result.content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif hasattr(block, "data"):
                    parts.append(f"[binary: {getattr(block, 'mime_type', 'unknown')}]")
                else:
                    parts.append(str(block))
            return "\n".join(parts) if parts else ""
        return str(content)
    return str(result)


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
        List of LangChain ``StructuredTool`` instances.
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

        async def _invoke(
            call_fn: Callable[..., Awaitable[object]] = call_tool_fn,
            name: str = captured_name,
            schema: dict[str, Any] = captured_schema,
            **kwargs: object,
        ) -> str:
            call_args = prepare_mcp_call_arguments(kwargs, schema)
            raw = await call_fn(name, call_args)
            return _normalize_call_result(raw)

        lc_tool = StructuredTool(
            name=tool_name,
            description=description,
            args_schema=args_model,
            coroutine=_invoke,
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
