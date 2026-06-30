"""MCP tool discovery layer — ``MCPAgent`` is not ``myrm_agent_harness.agent``.

``MCPAgent`` orchestrates multi-server MCP tool fetch/normalize; it does **not** import or
belong to the harness Agent runtime package. See ``toolkits/_ARCH.md`` § Naming disambiguation.

Provides MCP tool fetching capabilities:
- Fetches tools from multiple MCP servers
- Server-prefix isolation: ``mcp__{server}__{tool}`` naming prevents collisions and permission bypass
- Maintains tool-to-server mapping
- Supports parallel multi-server tool fetching
- Auto-truncates excessively long tool descriptions to prevent token waste
- Content block coercion: ``_coerce_content_block`` ensures only LLM-safe types (text, image) reach the API — ``file``, ``audio``, and unknown blocks are gracefully degraded to text, preventing 400 errors and session history poisoning
- Content boundary defense: ``_timeout_wrapper`` applies ``wrap_untrusted()`` to MCP tool string outputs, ensuring third-party server data receives the same 5-layer content boundary protection (Unicode folding, structural framing strip, marker sanitization, random boundary, pattern detection) as all built-in tools
- Upstream fault tolerance: ``_timeout_wrapper`` catches adapter-layer exceptions (NotImplementedError for AudioContent, ValueError for unknown types) from langchain_mcp_adapters, returning readable error messages instead of crashing
- Extracts MCP structuredContent from artifacts as supplementary text blocks
- Detects ext-apps ``_meta.ui.resourceUri`` and emits MCP App view events via progress_sink


[INPUT]
- client::MCPClientManager, MCPServerConfigProtocol (POS: MCP client management layer)
- config::parse_mcp_tool_name, sanitize_mcp_name_component, should_register_mcp_tool (POS: MCP configuration, name sanitization, tool name parsing, and per-server tool filter function)
- schema_utils::FlattenMeta, canonicalize_schema_for_cache, coerce_arguments_by_schema, flatten_deep_schema, flatten_json_schema, has_dot_keys, nest_flat_arguments (POS: MCP schema tolerance utilities)
- core.security.tool_registry::MCPAnnotations, SafetyMetadata, register_ptc_safety_metadata (POS: Tool metadata and permission mapping)
- agent.streaming.types::AgentEventType (POS: Framework-agnostic streaming event types)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: Runtime tool progress event sink)
- core.security.detection.content_boundary::wrap_untrusted (POS: 5-layer content boundary defense for MCP tool outputs)
- langchain_mcp_adapters (POS: MCP adapter library)

[OUTPUT]
- MCPAgent: MCP tool fetching, server mapping, content block coercion (file/audio/unknown→text), multimodal result normalization, content boundary defense (wrap_untrusted for all string outputs), upstream fault tolerance, ext-apps metadata emission, and safety annotation registration

[POS]
MCP tool discovery layer (not harness Agent runtime). Orchestrates multi-server tool discovery with parallel fetching,
server-prefix isolation (mcp__{server}__{tool} naming), per-server tool filtering
(include/exclude whitelist), description truncation, content block coercion
(file/audio/unknown types gracefully degraded to text for LLM API safety),
content boundary defense (wrap_untrusted for all string outputs against prompt injection),
upstream fault tolerance (catches adapter-layer NotImplementedError/ValueError),
multimodal result normalization (ImageContent passthrough + structuredContent
extraction), ext-apps UI metadata detection and SSE event emission, and safety
metadata registration. `process_session_tools()` is the single post-processing
chain shared by persistent-session actors and one-shot enumeration.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from myrm_agent_harness.core.security.tool_registry import (
    MCPAnnotations,
    SafetyMetadata,
    register_ptc_safety_metadata,
)

from .client import MCPClientManager, MCPServerConfigProtocol
from .config import parse_mcp_tool_name, sanitize_mcp_name_component, should_register_mcp_tool
from .schema_utils import (
    FlattenMeta,
    canonicalize_schema_for_cache,
    coerce_arguments_by_schema,
    flatten_deep_schema,
    flatten_json_schema,
    has_dot_keys,
    nest_flat_arguments,
)

logger = logging.getLogger(__name__)

# Auto-generated MCP servers (e.g. Swagger/OpenAPI converters) may embed
# 15-60 KB of API docs into tool descriptions, wasting massive tokens.
# 2048 chars ≈ 512 tokens — sufficient for core descriptions while
# capping 50 tools at ~25K tokens (vs. 750K+ without truncation).
_MAX_MCP_TOOL_DESCRIPTION_LEN = 2048

# Remote SSE/stdio handshakes occasionally drop the initial tool listing
# (empty result or timeout); a bounded retry makes enumeration reliable
# without masking a server that is genuinely tool-less or unreachable.
_TOOL_FETCH_MAX_ATTEMPTS = 3
_TOOL_FETCH_RETRY_BACKOFF = 0.3


class MCPAgent:
    """MCP agent core — provides tool fetching and server mapping."""

    def __init__(self) -> None:
        self._tool_server_mapping: dict[str, str] = {}

    def _get_tool_id(self, tool: BaseTool) -> str:
        """Get a unique identifier for a tool (name + description hash)."""
        tool_name = getattr(tool, "name", "unknown")
        tool_desc = getattr(tool, "description", "")
        return f"{tool_name}:{hash(tool_desc)}"

    @staticmethod
    def _apply_tool_filter(
        tools: list[BaseTool],
        server_name: str,
        tool_include: list[str] | None,
        tool_exclude: list[str] | None,
    ) -> list[BaseTool]:
        """Apply the per-server include/exclude whitelist to fetched tools.

        Runs at the single tool-fetch entry point so both direct and PTC-skill
        paths share identical filtering — filtered-out tools never reach the LLM,
        the permission engine, or PTC skill generation (config-time least privilege).
        """
        if not tool_include and not tool_exclude:
            return tools
        filtered = [t for t in tools if should_register_mcp_tool(t.name, tool_include, tool_exclude)]
        removed = len(tools) - len(filtered)
        if removed:
            logger.info(
                "MCP server '%s': tool filter kept %d/%d tools (%d removed by include/exclude)",
                server_name,
                len(filtered),
                len(tools),
                removed,
            )
        return filtered

    @staticmethod
    def _enforce_description_limits(tools: list[BaseTool]) -> None:
        """Truncate overlong MCP tool descriptions to prevent token waste."""
        limit = _MAX_MCP_TOOL_DESCRIPTION_LEN
        for tool in tools:
            desc = getattr(tool, "description", None) or ""
            if len(desc) > limit:
                logger.warning(
                    "MCP tool '%s' description truncated from %d to %d chars",
                    getattr(tool, "name", "?"),
                    len(desc),
                    limit,
                )
                tool.description = desc[:limit] + "..."

    @staticmethod
    def _extract_mcp_app_metadata(artifact: object) -> dict[str, object] | None:
        """Extract MCP Apps (ext-apps) metadata from an MCP artifact.

        Returns a dict with ``resource_uri`` and optionally ``structured_content``
        when the artifact carries ``_meta.ui.resourceUri`` (ext-apps standard).
        """
        if artifact is None:
            return None
        meta = artifact.get("_meta") if isinstance(artifact, dict) else getattr(artifact, "_meta", None)
        if not isinstance(meta, dict):
            return None
        ui = meta.get("ui")
        if not isinstance(ui, dict):
            return None
        resource_uri = ui.get("resourceUri")
        if not isinstance(resource_uri, str) or not resource_uri:
            return None
        structured = (
            artifact.get("structured_content")
            if isinstance(artifact, dict)
            else getattr(artifact, "structured_content", None)
        )
        result: dict[str, object] = {"resource_uri": resource_uri}
        if structured is not None:
            result["structured_content"] = structured
        return result

    @staticmethod
    def _coerce_content_block(block: dict[str, object]) -> dict[str, object]:
        """Coerce a LangChain content block to an LLM-safe type.

        ``langchain_mcp_adapters`` converts MCP ``ResourceLink`` to LangChain
        ``{type: "file"}`` blocks and ``EmbeddedResource`` blobs to similar
        non-standard types.  LLM APIs (Anthropic, OpenAI) only accept ``text``
        and ``image`` in tool results — sending ``file`` or unknown types causes
        400 errors and permanently poisons the session history (every subsequent
        turn replays the invalid block).

        This method acts as a safety boundary: ``text`` and well-formed ``image``
        blocks pass through unchanged; everything else is gracefully degraded to
        ``text`` so the LLM still receives the useful information (URLs, labels)
        without crashing.
        """
        block_type = block.get("type")

        if block_type == "text":
            return block

        if block_type == "image":
            if block.get("base64") or block.get("data") or block.get("url"):
                return block
            logger.warning("Degrading malformed image block (missing source) to text")
            return {"type": "text", "text": json.dumps(block, default=str)}

        if block_type == "file":
            url = block.get("url", "")
            mime = block.get("mime_type", "")
            label = f"[file: {url}]" if url else f"[file {mime}]"
            logger.warning("Degrading file block to text: %s", label)
            return {"type": "text", "text": label}

        logger.warning("Degrading unknown content block type '%s' to text", block_type)
        return {"type": "text", "text": json.dumps(block, default=str)}

    @staticmethod
    def _normalize_mcp_result(result: object) -> str | list[dict[str, object]]:
        """Normalize content_and_artifact tuple from langchain_mcp_adapters.

        langchain_mcp_adapters returns ``(list[ContentBlock], artifact | None)``
        where ContentBlock is ``{"type": "text", "text": "..."}`` or image/file
        blocks.  Every block is passed through ``_coerce_content_block`` to
        guarantee only LLM-safe types (``text``, ``image``) reach the API —
        preventing 400 errors and session history poisoning from ``file``,
        ``audio``, or unknown block types.

        When the coerced result contains **only** text blocks, returns a plain
        ``str`` for backward compatibility.  When image blocks are present,
        returns the full ``list[dict]`` so ToolNode can construct a multimodal
        ``ToolMessage`` that flows through the existing streaming pipeline
        (``event_handlers.TOOL_IMAGE_OUTPUT`` → frontend ``ToolImageGallery``).
        ``structuredContent`` from the MCP artifact is appended as a
        supplementary text block when present.
        """
        if isinstance(result, tuple) and len(result) == 2:
            content_blocks, artifact = result
            if isinstance(content_blocks, list):
                coerced: list[dict[str, object]] = [
                    MCPAgent._coerce_content_block(b) if isinstance(b, dict) else {"type": "text", "text": str(b)}
                    for b in content_blocks
                ]

                if artifact is not None:
                    structured = (
                        artifact.get("structured_content")
                        if isinstance(artifact, dict)
                        else getattr(artifact, "structured_content", None)
                    )
                    if structured is not None:
                        coerced.append(
                            {
                                "type": "text",
                                "text": json.dumps(structured, ensure_ascii=False),
                            }
                        )

                has_image = any(b.get("type") == "image" for b in coerced)
                if has_image:
                    return coerced

                texts: list[str] = []
                for block in coerced:
                    texts.append(str(block.get("text", "") or ""))
                return "\n".join(texts) if texts else ""
            if isinstance(content_blocks, str):
                return content_blocks
        if isinstance(result, str):
            return result
        return str(result)

    @staticmethod
    def _wrap_tools_with_timeout(tools: list[BaseTool], timeout: float, max_output_chars: int = 100_000) -> None:
        """Wrap MCP tool execution with asyncio.timeout, normalize, and guard output size."""
        from myrm_agent_harness.core.security.detection.content_boundary import wrap_untrusted

        for tool in tools:
            original_coroutine = tool.coroutine
            if original_coroutine is None:
                continue

            tool_name = tool.name

            async def _timeout_wrapper(
                *args: object,
                _orig: object = original_coroutine,
                _name: str = tool_name,
                _timeout: float = timeout,
                _max_chars: int = max_output_chars,
                **kwargs: object,
            ) -> str | list[dict[str, object]]:
                try:
                    async with asyncio.timeout(_timeout):
                        raw = await _orig(*args, **kwargs)  # type: ignore[misc]
                        normalized = MCPAgent._normalize_mcp_result(raw)
                        await MCPAgent._emit_mcp_app_event(raw, _name)
                        if isinstance(normalized, str) and len(normalized) > _max_chars:
                            original_len = len(normalized)
                            discarded = original_len - _max_chars
                            normalized = (
                                f"{normalized[:_max_chars]}\n\n"
                                f"[Output truncated: showing first {_max_chars:,} of {original_len:,} chars. "
                                f"Remaining {discarded:,} chars were discarded to fit context budget.]"
                            )
                            logger.warning(
                                "MCP tool '%s' output truncated: %d → %d chars",
                                _name, original_len, _max_chars,
                            )
                        if isinstance(normalized, str):
                            normalized = wrap_untrusted(normalized, source=f"mcp:{_name}")
                        return normalized
                except TimeoutError:
                    error_msg = f"MCP tool '{_name}' timed out after {_timeout}s. Server may be slow or unresponsive."
                    logger.error(error_msg)
                    return error_msg
                except (NotImplementedError, ValueError, TypeError) as exc:
                    error_msg = f"MCP tool '{_name}' returned unsupported content: {exc}"
                    logger.warning(error_msg)
                    return error_msg

            tool.coroutine = _timeout_wrapper
            # Override response_format to prevent ToolNode from tuple-destructuring
            if hasattr(tool, "response_format"):
                tool.response_format = "content"

    @staticmethod
    async def _emit_mcp_app_event(raw_result: object, tool_name: str) -> None:
        """Emit an MCP_APP_VIEW event if the raw result carries ext-apps UI metadata."""
        if not isinstance(raw_result, tuple) or len(raw_result) != 2:
            return
        _, artifact = raw_result
        mcp_app_meta = MCPAgent._extract_mcp_app_metadata(artifact)
        if mcp_app_meta is None:
            return
        from myrm_agent_harness.core.events import AgentEventType
        from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

        sink = get_tool_progress_sink()
        if sink is None:
            return
        server_name = ""
        parsed = parse_mcp_tool_name(tool_name)
        if parsed is not None:
            server_name = parsed[0]
        event: dict[str, object] = {
            "type": AgentEventType.TOOL_END.value,
            "tool_name": tool_name,
            "mcp_app": {
                "resource_uri": mcp_app_meta["resource_uri"],
                "server_name": server_name,
            },
        }
        structured = mcp_app_meta.get("structured_content")
        if structured is not None:
            event["mcp_app"]["structured_content"] = structured  # type: ignore[index]
        try:
            await sink.emit(event)
        except Exception as exc:
            logger.debug("Failed to emit mcp_app event for tool '%s': %s", tool_name, exc)

    @staticmethod
    def _sanitize_tools(tools: list[BaseTool]) -> None:
        """Sanitize tool schemas: $ref resolution -> canonicalize -> deep-flatten -> coerce -> nest.

        Full error-tolerance chain for MCP tool parameters:
        1. Resolve $ref pointers inline
        2. Canonicalize key ordering for prompt prefix cache stability
        3. Flatten deeply-nested schemas to dot-path notation (for LLM compatibility)
        4. Wrap execution with type coercion + argument nesting restoration
        """
        for tool in tools:
            flatten_meta = FlattenMeta(was_flattened=False)

            if hasattr(tool, "args_schema") and isinstance(tool.args_schema, dict):
                # Step 1: Resolve $ref pointers
                tool.args_schema = flatten_json_schema(tool.args_schema)
                # Step 2: Canonicalize key ordering for prefix cache stability
                tool.args_schema = canonicalize_schema_for_cache(tool.args_schema)  # type: ignore[assignment]
                # Step 3: Flatten deep nesting to dot-path notation
                tool.args_schema, flatten_meta = flatten_deep_schema(tool.args_schema)

            # Step 4: Wrap execution with type coercion + argument nesting
            original_coroutine = getattr(tool, "coroutine", None)
            if original_coroutine:
                raw_schema = getattr(tool, "args_schema", None)
                schema_for_coercion = (
                    raw_schema
                    if isinstance(raw_schema, dict)
                    else getattr(raw_schema, "schema", lambda: {})()
                    if raw_schema is not None and hasattr(raw_schema, "schema")
                    else getattr(raw_schema, "model_json_schema", lambda: {})()
                    if raw_schema is not None and hasattr(raw_schema, "model_json_schema")
                    else {}
                )

                async def _coercion_wrapper(
                    *args,
                    _orig=original_coroutine,
                    _schema=schema_for_coercion,
                    _meta=flatten_meta,
                    **kwargs,
                ):
                    coerced_kwargs = coerce_arguments_by_schema(_schema, kwargs)
                    # Restore nested structure only if schema was flattened AND model used dot-keys
                    if _meta.was_flattened and has_dot_keys(coerced_kwargs):
                        coerced_kwargs = nest_flat_arguments(coerced_kwargs)
                    return await _orig(*args, **coerced_kwargs)

                tool.coroutine = _coercion_wrapper

    def _store_tool_server_mapping(self, tools: list[BaseTool], server_name: str) -> None:
        """Store tool-to-server name mapping."""
        for tool in tools:
            tool_id = self._get_tool_id(tool)
            self._tool_server_mapping[tool_id] = server_name

    @staticmethod
    def _register_tool_annotations(tools: list[BaseTool], server_name: str) -> None:
        """Extract and register MCP native annotations into PTC safety registry."""
        skill_name = server_name.replace("-", "_").lower()
        if not skill_name.startswith("mcp_"):
            skill_name = f"mcp_{skill_name}"
        if not skill_name.endswith("_skill"):
            skill_name = f"{skill_name}_skill"

        for tool in tools:
            meta = getattr(tool, "metadata", {}) or {}

            annotations: MCPAnnotations = {}
            for key in ["readOnlyHint", "idempotentHint", "destructiveHint", "openWorldHint"]:
                if key in meta:
                    annotations[key] = bool(meta[key])  # type: ignore[misc]

            is_read_only = annotations.get("readOnlyHint", False)
            safety_meta = SafetyMetadata(
                is_read_only=is_read_only,
                is_concurrent_safe=is_read_only,
                is_destructive=annotations.get("destructiveHint", False),
                is_open_world=annotations.get("openWorldHint", False),
                is_idempotent=annotations.get("idempotentHint", False),
            )

            register_ptc_safety_metadata(skill_name, tool.name, safety_meta, annotations)

    @staticmethod
    def _prefix_tool_names(tools: list[BaseTool], server_name: str) -> None:
        """Add ``mcp__{server}__{tool}`` prefix to each tool name.

        Double-underscore delimiters eliminate the ambiguity that single
        underscores cause when server names contain underscores (e.g.
        ``mcp_a_b_tool`` could be server ``a`` + tool ``b_tool`` or
        server ``a_b`` + tool ``tool``).  With ``__`` the split is
        always unambiguous: ``mcp__{server}__{tool}``.

        Also prevents permission bypass when an MCP tool name
        coincidentally matches a built-in tool name.
        """
        safe_server = sanitize_mcp_name_component(server_name)
        for tool in tools:
            safe_tool = sanitize_mcp_name_component(tool.name)
            tool.name = f"mcp__{safe_server}__{safe_tool}"

    @staticmethod
    def process_session_tools(
        tools: list[BaseTool],
        server_name: str,
        tool_include: list[str] | None,
        tool_exclude: list[str] | None,
        execute_timeout: float,
        max_output_chars: int = 100_000,
    ) -> list[BaseTool]:
        """Apply the full post-processing chain to tools bound to a live session.

        Single source of truth shared by the persistent-session actor and the
        one-shot enumeration path, so direct and PTC routes get identical
        filtering, schema sanitization, execution timeout, and safety metadata.
        Returns the filtered, in-place-wrapped tool list (timeout(coercion(call))).

        Pipeline order:
        filter (uses original names) → prefix → description limit →
        sanitize (schema) → timeout + output guard → annotations.
        """
        tools = MCPAgent._apply_tool_filter(tools, server_name, tool_include, tool_exclude)
        MCPAgent._prefix_tool_names(tools, server_name)
        MCPAgent._enforce_description_limits(tools)
        MCPAgent._sanitize_tools(tools)
        MCPAgent._wrap_tools_with_timeout(tools, execute_timeout, max_output_chars)
        MCPAgent._register_tool_annotations(tools, server_name)
        return tools

    def get_tool_server_name(self, tool: BaseTool) -> str:
        """Get the server name associated with a tool."""
        tool_id = self._get_tool_id(tool)
        return self._tool_server_mapping.get(tool_id, "unknown_server")

    def get_server_name_by_tool_name(self, tool_name: str) -> str:
        """Look up the server name by tool name."""
        for tool_id, server_name in self._tool_server_mapping.items():
            if tool_id.startswith(f"{tool_name}:"):
                return server_name
        return "unknown_server"

    async def get_tools_from_server(
        self,
        client: MultiServerMCPClient,
        server_name: str,
        connect_timeout: float = 15.0,
    ) -> tuple[str, list[BaseTool], str | None]:
        """Fetch tools from a single MCP server with connection timeout and bounded retry.

        Transient enumeration failures (empty listing, timeout, connection drop) are
        retried up to ``_TOOL_FETCH_MAX_ATTEMPTS`` times; genuine cancellation is never
        retried. The last failure reason is returned so callers keep their error contract.
        """
        last_error = "not found tools"
        for attempt in range(1, _TOOL_FETCH_MAX_ATTEMPTS + 1):
            try:
                async with asyncio.timeout(connect_timeout):
                    tools = await client.get_tools(server_name=server_name)
                if tools:
                    return server_name, tools, None
                last_error = "not found tools"
            except asyncio.CancelledError as e:
                from .errors import reraise_if_genuine_cancel

                reraise_if_genuine_cancel(e)
                logger.warning(f"Server {server_name} cancelled by MCP SDK")
                return server_name, [], "cancelled by SDK"
            except TimeoutError:
                last_error = f"connection timed out after {connect_timeout}s"
                logger.warning(
                    "MCP server '%s' enumeration timed out after %.1fs (attempt %d/%d)",
                    server_name,
                    connect_timeout,
                    attempt,
                    _TOOL_FETCH_MAX_ATTEMPTS,
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "MCP server '%s' enumeration failed (attempt %d/%d): %s",
                    server_name,
                    attempt,
                    _TOOL_FETCH_MAX_ATTEMPTS,
                    e,
                )

            if attempt < _TOOL_FETCH_MAX_ATTEMPTS:
                await asyncio.sleep(_TOOL_FETCH_RETRY_BACKOFF)

        return server_name, [], last_error

    async def get_tools(self, mcp_config: Sequence[MCPServerConfigProtocol] | None = None) -> list[BaseTool]:
        """Get all available MCP tools."""
        _, tools = await self.get_tools_with_client(mcp_config)
        return tools

    async def get_tools_with_client(
        self, mcp_config: Sequence[MCPServerConfigProtocol] | None = None
    ) -> tuple[MultiServerMCPClient, list[BaseTool]]:
        """Get all available MCP tools, also returning the client instance.

        Returns:
            tuple[MultiServerMCPClient, list[BaseTool]]: (client, tools)
        """
        self._tool_server_mapping.clear()
        client = await MCPClientManager.initialize_client(mcp_config)

        if not client.connections:
            return client, []

        server_names = list(client.connections.keys())
        all_tools: list[BaseTool] = []

        # Build per-server timeout, output-limit, and tool-filter mappings
        connect_timeout_by_server: dict[str, float] = {}
        execute_timeout_by_server: dict[str, float] = {}
        max_output_chars_by_server: dict[str, int] = {}
        tool_filter_by_server: dict[str, tuple[list[str] | None, list[str] | None]] = {}
        if mcp_config:
            for cfg in mcp_config:
                connect_timeout_by_server[cfg.name] = cfg.connect_timeout
                execute_timeout_by_server[cfg.name] = cfg.execute_timeout
                max_output_chars_by_server[cfg.name] = getattr(cfg, "max_output_chars", 100_000)
                tool_filter_by_server[cfg.name] = (
                    getattr(cfg, "tool_include", None),
                    getattr(cfg, "tool_exclude", None),
                )

        if len(server_names) == 1:
            server_name, tools, error = await self.get_tools_from_server(
                client,
                server_names[0],
                connect_timeout_by_server.get(server_names[0], 15.0),
            )
            if error:
                raise Exception(f"Failed to get tools from {server_name}: {error}")

            include, exclude = tool_filter_by_server.get(server_name, (None, None))
            tools = self.process_session_tools(
                tools,
                server_name,
                include,
                exclude,
                execute_timeout_by_server.get(server_name, 120.0),
                max_output_chars_by_server.get(server_name, 100_000),
            )
            self._store_tool_server_mapping(tools, server_name)
            all_tools = tools
        else:
            tasks = [
                self.get_tools_from_server(client, sn, connect_timeout_by_server.get(sn, 15.0)) for sn in server_names
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Task failed: {result}")
                    raise result

                if isinstance(result, tuple) and len(result) == 3:
                    server_name, tools, error = result
                    if error:
                        raise Exception(f"Failed to get tools from {server_name}: {error}")

                    include, exclude = tool_filter_by_server.get(server_name, (None, None))
                    tools = self.process_session_tools(
                        tools,
                        server_name,
                        include,
                        exclude,
                        execute_timeout_by_server.get(server_name, 120.0),
                        max_output_chars_by_server.get(server_name, 100_000),
                    )
                    self._store_tool_server_mapping(tools, server_name)
                    all_tools.extend(tools)

        return client, all_tools
