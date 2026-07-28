"""Tool Search Bridge — progressive tool disclosure for deferred MCP tools.

[INPUT]
- agent._factory.mcp_routing::_input_schema (POS: MCP three-path routing, schema extraction)
- toolkits.mcp.config::parse_mcp_tool_name (POS: MCP Configuration, tool name parsing)

[OUTPUT]
- build_bridge_tools(): create the 3 LangChain bridge tools for injection into the agent
- BridgeCatalog: BM25-indexed deferred tool catalog
- DeferredServerBundle: data structure for bridge-routed servers with preserved tool instances
- register_deferred_tools/clear_deferred_tools: session-scoped deferred tool registry

[POS]
Progressive tool disclosure bridge. When aggregate MCP direct tools exceed the token budget,
medium servers are routed here instead of being demoted to PTC skills. Deferred tools retain
native function calling via tool_call proxy — avoiding LLM interpretation overhead of PTC SOPs.
"""

from __future__ import annotations

import contextvars
import json
import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.toolkits.mcp.config import MCPConfig

logger = logging.getLogger(__name__)

TOOL_SEARCH_NAME = "mcp_tool_search"
TOOL_DESCRIBE_NAME = "mcp_tool_describe"
TOOL_CALL_NAME = "mcp_tool_call"
BRIDGE_TOOL_NAMES = frozenset({TOOL_SEARCH_NAME, TOOL_DESCRIBE_NAME, TOOL_CALL_NAME})

CHARS_PER_TOKEN = 4.0
LISTING_MAX_TOKENS = 12000
SHORT_DESC_MAX_CHARS = 80

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Simple alphanumeric tokenization for BM25 search."""
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _short_desc(description: str, max_chars: int = SHORT_DESC_MAX_CHARS) -> str:
    """First sentence of a tool description, clipped to max_chars."""
    text = " ".join((description or "").split())
    if not text:
        return ""
    end = re.search(r"[.!?\n]", text)
    if end:
        text = text[: end.start() + 1]
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(",;: ") + "…"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One deferred MCP tool retained for bridge-mediated access."""

    name: str
    original_name: str
    description: str
    server_name: str
    tokens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeferredServerBundle:
    """A server routed to the bridge path with its tools preserved."""

    config: MCPConfig
    tools: tuple[BaseTool, ...]
    schema_tokens: int


class BridgeCatalog:
    """BM25-indexed catalog of deferred MCP tools.

    Rebuilt per-session from the current tool definitions (stateless across sessions).
    Supports keyword search with substring fallback.
    """

    def __init__(self, entries: list[CatalogEntry]) -> None:
        self._entries = entries
        self._by_name: dict[str, CatalogEntry] = {e.name: e for e in entries}

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> list[CatalogEntry]:
        return self._entries

    def get(self, name: str) -> CatalogEntry | None:
        return self._by_name.get(name)

    def search(self, query: str, limit: int = 5) -> list[CatalogEntry]:
        """BM25-rank entries against query, with substring fallback."""
        if not self._entries or limit <= 0:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        n_docs = len(self._entries)
        doc_freq: dict[str, int] = {}
        for entry in self._entries:
            for t in set(entry.tokens):
                doc_freq[t] = doc_freq.get(t, 0) + 1
        avg_dl = sum(len(e.tokens) for e in self._entries) / max(n_docs, 1)

        scored: list[tuple[float, CatalogEntry]] = []
        for entry in self._entries:
            score = _bm25_score(query_tokens, entry.tokens, avg_dl, doc_freq, n_docs)
            if score > 0:
                scored.append((score, entry))

        if not scored:
            ql = query.lower()
            for entry in self._entries:
                if ql in entry.name.lower() or ql in entry.description.lower():
                    scored.append((0.1, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    avg_dl: float,
    doc_freq: dict[str, int],
    n_docs: int,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """Standard BM25 scoring for a single document."""
    if not doc_tokens:
        return 0.0
    dl = len(doc_tokens)
    doc_tf: dict[str, int] = {}
    for t in doc_tokens:
        doc_tf[t] = doc_tf.get(t, 0) + 1

    score = 0.0
    for q in query_tokens:
        df = doc_freq.get(q, 0)
        if df == 0:
            continue
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        tf = doc_tf.get(q, 0)
        if tf == 0:
            continue
        norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / max(avg_dl, 1.0)))
        score += idf * norm
    return score


def build_catalog(bundles: Sequence[DeferredServerBundle]) -> BridgeCatalog:
    """Build a BridgeCatalog from deferred server bundles."""
    entries: list[CatalogEntry] = []
    for bundle in bundles:
        for tool in bundle.tools:
            search_text = _build_search_text(tool)
            entries.append(
                CatalogEntry(
                    name=tool.name,
                    original_name=_extract_original_name(tool.name),
                    description=tool.description or "",
                    server_name=bundle.config.name,
                    tokens=tuple(_tokenize(search_text)),
                )
            )
    return BridgeCatalog(entries)


def _build_search_text(tool: BaseTool) -> str:
    """Build searchable text from a tool's name, description, and param names."""
    from myrm_agent_harness.agent._factory.mcp_routing import _input_schema

    name_words = tool.name.replace("_", " ").replace(".", " ").replace("-", " ")
    desc = tool.description or ""
    schema = _input_schema(tool)
    param_names = " ".join((schema.get("properties") or {}).keys())
    return f"{name_words} {desc} {param_names}"


def _extract_original_name(prefixed_name: str) -> str:
    """Extract the original tool name from mcp__{server}__{tool} format."""
    from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

    parsed = parse_mcp_tool_name(prefixed_name)
    if parsed:
        return parsed[1]
    return prefixed_name


def build_catalog_listing(catalog: BridgeCatalog, max_tokens: int = LISTING_MAX_TOKENS) -> str | None:
    """Render a grouped catalog listing for embedding in tool_search description.

    Tiered degradation:
    1. Full listing (name: short description), grouped by server
    2. Names-only listing
    3. Server-level summary (server name + tool count)
    4. None (over budget in all forms)
    """
    if catalog.size == 0:
        return None

    groups: dict[str, list[tuple[str, str]]] = {}
    for entry in catalog.entries:
        groups.setdefault(entry.server_name, []).append(
            (entry.name, _short_desc(entry.description))
        )

    def _fits(text: str) -> bool:
        return math.ceil(len(text) / CHARS_PER_TOKEN) <= max_tokens

    header = (
        f"Deferred MCP tools (schemas via `{TOOL_DESCRIBE_NAME}`, "
        f"invoke via `{TOOL_CALL_NAME}`):"
    )

    # Tier 1: full (name: description)
    full_lines = [header]
    for label in sorted(groups):
        tools = sorted(groups[label])
        full_lines.append(f"\n{label} ({len(tools)} tools):")
        for name, desc in tools:
            full_lines.append(f"  - {name}: {desc}" if desc else f"  - {name}")
    full_text = "\n".join(full_lines)
    if _fits(full_text):
        return full_text

    # Tier 2: names-only
    names_lines = [header]
    for label in sorted(groups):
        tools = sorted(groups[label])
        names_lines.append(f"\n{label} ({len(tools)} tools):")
        names_lines.append("  " + ", ".join(name for name, _ in tools))
    names_text = "\n".join(names_lines)
    if _fits(names_text):
        return names_text

    # Tier 3: server summary
    summary_lines = [header]
    for label in sorted(groups):
        summary_lines.append(
            f"  - {label}: {len(groups[label])} tools (discover via `{TOOL_SEARCH_NAME}`)"
        )
    summary_text = "\n".join(summary_lines)
    if _fits(summary_text):
        return summary_text

    return None


def _validate_required_args(tool: BaseTool, arguments: dict[str, Any]) -> str | None:
    """Check required arguments before dispatch; return error JSON if missing.

    LLMs routinely skip tool_describe and blind-call with missing required args,
    producing opaque downstream errors. Returning the schema here lets the model
    self-repair in one round-trip instead of looping on cryptic failures.
    """
    from myrm_agent_harness.agent._factory.mcp_routing import _input_schema

    try:
        schema = _input_schema(tool)
        required = schema.get("required")
        if not isinstance(required, list) or not required:
            return None
        missing = [r for r in required if isinstance(r, str) and r not in arguments]
        if not missing:
            return None
        return json.dumps(
            {
                "error": (
                    f"tool_call to '{tool.name}' is missing required argument(s): "
                    f"{', '.join(missing)}. The tool was NOT invoked."
                ),
                "parameters": schema,
                "hint": "Retry tool_call with 'arguments' matching the parameters schema above.",
            },
            ensure_ascii=False,
        )
    except Exception:
        return None


def build_bridge_tools(catalog: BridgeCatalog) -> list[BaseTool]:
    """Create the 3 LangChain bridge tools for agent injection.

    These tools are stateless — the catalog is captured at build time and
    the tool_call dispatches to the live MCP connection pool.
    """
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    listing = build_catalog_listing(catalog)

    # --- tool_search schema ---
    class ToolSearchInput(BaseModel):
        query: str = Field(description="Keywords describing the capability you need (e.g. 'create github issue')")
        limit: int = Field(default=5, ge=1, le=20, description="Max results to return")

    search_desc = (
        f"Search {catalog.size} deferred MCP tools loaded on demand. "
        "Returns matches with name and description. Follow with "
        f"`{TOOL_DESCRIBE_NAME}` to load full schema, then `{TOOL_CALL_NAME}` to invoke."
    )
    if listing:
        search_desc += "\n\n" + listing

    def _tool_search(query: str, limit: int = 5) -> str:
        hits = catalog.search(query, limit=limit)
        return json.dumps(
            {
                "query": query,
                "total_available": catalog.size,
                "matches": [
                    {"name": h.name, "server": h.server_name, "description": h.description[:400]}
                    for h in hits
                ],
            },
            ensure_ascii=False,
        )

    # --- tool_describe schema ---
    class ToolDescribeInput(BaseModel):
        name: str = Field(description="Exact tool name (as returned by mcp_tool_search)")

    def _tool_describe(name: str) -> str:
        from myrm_agent_harness.agent._factory.mcp_routing import _input_schema

        entry = catalog.get(name)
        if entry is None:
            return json.dumps(
                {"error": f"'{name}' not found. Use {TOOL_SEARCH_NAME} to discover available tools."},
                ensure_ascii=False,
            )
        # Find the actual BaseTool to extract full schema
        tool_obj = _find_deferred_tool(name)
        if tool_obj is None:
            return json.dumps(
                {"error": f"'{name}' catalog entry exists but tool instance not available."},
                ensure_ascii=False,
            )
        schema = _input_schema(tool_obj)
        return json.dumps(
            {
                "name": name,
                "server": entry.server_name,
                "description": entry.description,
                "parameters": schema,
            },
            ensure_ascii=False,
        )

    # --- tool_call schema ---
    class ToolCallInput(BaseModel):
        name: str = Field(description="Exact tool name to invoke")
        arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments matching the tool's schema")

    async def _tool_call(name: str, arguments: dict[str, Any] | None = None) -> str:
        entry = catalog.get(name)
        if entry is None:
            return json.dumps(
                {"error": f"'{name}' not found. Use {TOOL_SEARCH_NAME} to discover available tools."},
                ensure_ascii=False,
            )
        tool_obj = _find_deferred_tool(name)
        if tool_obj is None:
            return json.dumps(
                {"error": f"'{name}' tool instance not available. Connection may have been lost."},
                ensure_ascii=False,
            )
        # Validate required arguments before dispatching (prevents blind-call loops)
        validation_error = _validate_required_args(tool_obj, arguments or {})
        if validation_error is not None:
            return validation_error
        try:
            result = await tool_obj.ainvoke(arguments or {})
            if isinstance(result, str):
                return result
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("Bridge tool_call '%s' failed: %s", name, e)
            return json.dumps({"error": f"Tool execution failed: {e}"}, ensure_ascii=False)

    tool_search = StructuredTool.from_function(
        func=_tool_search,
        name=TOOL_SEARCH_NAME,
        description=search_desc,
        args_schema=ToolSearchInput,
    )
    tool_describe = StructuredTool.from_function(
        func=_tool_describe,
        name=TOOL_DESCRIBE_NAME,
        description=(
            f"Load the full JSON parameter schema for a tool returned by `{TOOL_SEARCH_NAME}`. "
            f"Required before `{TOOL_CALL_NAME}` if the tool's parameters are unknown."
        ),
        args_schema=ToolDescribeInput,
    )
    tool_call = StructuredTool.from_function(
        coroutine=_tool_call,
        name=TOOL_CALL_NAME,
        description=(
            "Invoke a deferred MCP tool by name with arguments. "
            f"Argument shape must match the schema from `{TOOL_DESCRIBE_NAME}`. "
            "Guardrails and timeouts apply identically to direct tools."
        ),
        args_schema=ToolCallInput,
    )
    return [tool_search, tool_describe, tool_call]


# ---------------------------------------------------------------------------
# Deferred tool registry — ContextVar-scoped for session isolation
# ---------------------------------------------------------------------------

_deferred_tools_var: contextvars.ContextVar[dict[str, BaseTool]] = contextvars.ContextVar(
    "bridge_deferred_tools", default={}
)


def register_deferred_tools(bundles: Sequence[DeferredServerBundle]) -> None:
    """Register deferred tool instances for bridge dispatch (session-scoped)."""
    registry: dict[str, BaseTool] = {}
    for bundle in bundles:
        for tool in bundle.tools:
            registry[tool.name] = tool
    _deferred_tools_var.set(registry)


def _find_deferred_tool(name: str) -> BaseTool | None:
    """Look up a deferred tool by its prefixed name."""
    return _deferred_tools_var.get().get(name)


def clear_deferred_tools() -> None:
    """Clear the deferred tool registry (for testing/cleanup)."""
    _deferred_tools_var.set({})


__all__ = [
    "BRIDGE_TOOL_NAMES",
    "TOOL_CALL_NAME",
    "TOOL_DESCRIBE_NAME",
    "TOOL_SEARCH_NAME",
    "BridgeCatalog",
    "CatalogEntry",
    "DeferredServerBundle",
    "build_bridge_tools",
    "build_catalog",
    "build_catalog_listing",
    "clear_deferred_tools",
    "register_deferred_tools",
]
