"""MCP tool schema → LangChain BaseTool converter.

Converts MCP ``Tool`` objects (from ``client.list_tools()``) into
``SafeStructuredTool`` instances (a ``StructuredTool`` subclass whose ``_arun``
never swallows ``config``/``run_manager`` arguments — see
``structured_tool.py``) whose ``ainvoke`` calls the provided session/client's
``call_tool`` method. The input schema is normalized:
``$ref``/``$defs`` are inlined, property-level const unions collapse into
``enum`` (Rust/TypeScript servers), and top-level composite keywords
(``anyOf``/``oneOf``/``allOf``) are flattened so MCPServer nested/optional
models and kimi-cu-style multi-branch tools never degrade to empty schemas.

The normalized JSON Schema dict is passed through unchanged as the
``SafeStructuredTool`` ``args_schema`` — never rebuilt into a Pydantic model.
This preserves every semantic detail (``description``, ``enum``,
``minimum``/``maximum``, nested ``properties``) for the LLM: LangChain's
``convert_to_openai_tool`` serializes a dict ``args_schema`` verbatim,
matching how the official ``langchain-mcp-adapters`` and Hermes bridge MCP
tools. Runtime type coercion/restructuring is owned by
``tool_processing.sanitize_tools``' dict pipeline (``flatten_json_schema`` →
``canonicalize_schema_for_cache`` → ``flatten_deep_schema`` → coerce → nest),
which was already designed for dict schemas.

The coroutine returns the raw ``mcp.types.CallToolResult`` from ``call_tool``
unchanged — result normalization (is_error detection, content-block coercion,
multimodal passthrough, structured_content merging, ext-apps metadata) is
owned by ``result_processing.normalize_mcp_result`` /
``emit_mcp_app_event`` in the single post-processing chain
(``MCPAgent.process_session_tools``), so rich output is never flattened here.

[INPUT]
- mcp.types::Tool (POS: MCP tool schema type)
- mcp.ClientSession (POS: MCP SDK 2.x high-level client over stream transports)
- schema::collapse_const_unions, flatten_top_level_composite, flatten_json_schema, prepare_mcp_call_arguments (POS: MCP inbound tool schema normalization)

[OUTPUT]
- convert_mcp_tools: MCP Tool list → LangChain SafeStructuredTool list

[POS]
MCP-to-LangChain tool schema bridge using ``mcp`` SDK 2.x natively.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from myrm_agent_harness.toolkits.mcp.schema import (
    collapse_const_unions,
    flatten_json_schema,
    flatten_top_level_composite,
    prepare_mcp_call_arguments,
)
from myrm_agent_harness.toolkits.mcp.structured_tool import SafeStructuredTool

logger = logging.getLogger(__name__)


def convert_mcp_tools(
    tools: list[Any],
    call_tool_fn: Callable[..., Awaitable[object]],
    server_name: str = "",
) -> list[SafeStructuredTool]:
    """Convert MCP Tool objects to LangChain SafeStructuredTool instances.

    Args:
        tools: List of ``mcp.types.Tool`` objects from ``client.list_tools()``.
        call_tool_fn: Async callable ``(name, arguments) -> CallToolResult``.
            Typically ``client.call_tool``.
        server_name: Server name for logging.

    Returns:
        List of LangChain ``SafeStructuredTool`` instances.  Each tool's
        coroutine resolves ``CallToolResult`` from ``call_tool_fn`` unchanged —
        content normalization is deferred to ``MCPAgent`` (see module docstring).
    """
    result: list[SafeStructuredTool] = []
    for tool in tools:
        tool_name: str = tool.name
        description: str = getattr(tool, "description", "") or ""
        input_schema: dict[str, Any] = getattr(tool, "input_schema", None) or {}
        if isinstance(input_schema, str):
            input_schema = json.loads(input_schema)
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}

        # Resolve $ref/$defs inline, collapse property-level const unions into
        # enums, then flatten top-level composite branches: MCPServer emits
        # nested/optional models as $defs + $ref (no `type`), Rust/TypeScript
        # servers declare closed value sets as `anyOf` const unions, and
        # kimi-cu-style tools declare alternatives via oneOf/anyOf — without
        # normalization the LLM would see `$ref` placeholders, bare scalars,
        # or an empty schema. Deterministic and idempotent — a plain schema
        # passes through unchanged.
        ref_resolved = flatten_json_schema(input_schema)
        const_collapsed = collapse_const_unions(ref_resolved)
        composite_flattened = flatten_top_level_composite(const_collapsed)

        # Flattening may fold mutual-exclusivity hints into the schema-level
        # description (e.g. oneOf alternatives). The schema dict carries it
        # through to the LLM untouched, so no separate description splice is
        # needed — unlike a Pydantic args model, which would drop it.
        input_schema = composite_flattened

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

        lc_tool = SafeStructuredTool(
            name=tool_name,
            description=description,
            args_schema=input_schema,
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
