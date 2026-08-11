"""MCP tool discovery layer — ``MCPAgent`` is not ``myrm_agent_harness.agent``.

``MCPAgent`` orchestrates multi-server MCP tool fetch/normalize; it does **not** import or
belong to the harness Agent runtime package. See ``toolkits/_ARCH.md`` § Naming disambiguation.

Provides MCP tool fetching capabilities:
- Fetches tools from multiple MCP servers via ``mcp.client.Client`` (SDK 2.x)
- Server-prefix isolation: ``mcp__{server}__{tool}`` naming prevents collisions and permission bypass
- Maintains tool-to-server mapping
- Supports parallel multi-server tool fetching
- Auto-truncates excessively long tool descriptions to prevent token waste
- Content block coercion: ``_coerce_content_block`` ensures only LLM-safe types (text, image) reach the API — ``file``, ``audio``, and unknown blocks are gracefully degraded to text, preventing 400 errors and session history poisoning
- Content boundary defense: ``_timeout_wrapper`` applies ``wrap_untrusted()`` to MCP tool string outputs, ensuring third-party server data receives the same 5-layer content boundary protection (Unicode folding, structural framing strip, marker sanitization, random boundary, pattern detection) as all built-in tools
- Upstream fault tolerance: ``_timeout_wrapper`` catches adapter-layer exceptions (NotImplementedError for AudioContent, ValueError for unknown types), returning ``redact_sensitive_text``-sanitized error messages instead of crashing — prevents third-party exception messages from leaking credentials
- Auth error detection: ``_timeout_wrapper`` catches ``httpx2.HTTPStatusError(401)`` from the MCP transport, returns a clear re-authorization message to the Agent, and emits ``MCPAuthExpiredEvent`` (with redacted error detail) to trigger the existing toast/SSE notification chain
- Extracts MCP structuredContent from artifacts as supplementary text blocks
- Detects ext-apps ``_meta.ui.resourceUri`` and emits MCP App view events via progress_sink

[INPUT]
- client::MCPClientManager, MCPServerConfigProtocol (POS: MCP client management layer)
- tool_converter::convert_mcp_tools (POS: MCP tool → LangChain BaseTool converter)
- config::parse_mcp_tool_name, sanitize_mcp_name_component, should_register_mcp_tool (POS: MCP configuration, name sanitization, tool name parsing, and per-server tool filter function)
- schema_utils::FlattenMeta, canonicalize_schema_for_cache, coerce_arguments_by_schema, prepare_mcp_call_arguments, flatten_deep_schema, flatten_json_schema, has_dot_keys, nest_flat_arguments (POS: MCP schema tolerance utilities)
- core.security.tool_registry::MCPAnnotations, SafetyMetadata, register_ptc_safety_metadata (POS: Tool metadata and permission mapping)
- agent.streaming.types::AgentEventType (POS: Framework-agnostic streaming event types)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: Runtime tool progress event sink)
- core.security.detection.content_boundary::wrap_untrusted (POS: 5-layer content boundary defense for MCP tool outputs)
- core.security.redact::redact_sensitive_text (POS: Regex-based secret redaction for API keys, tokens, passwords in exception messages)
- runtime.events::get_event_bus (wired via auth_notify at runtime import)
- runtime.events.system_events::MCPAuthExpiredEvent (published by runtime handler)
- httpx2::HTTPStatusError (POS: HTTP status error for 401 auth detection)

[OUTPUT]
- MCPAgent: MCP tool fetching, server mapping, content block coercion (file/audio/unknown→text), multimodal result normalization, content boundary defense (wrap_untrusted for all string outputs), upstream fault tolerance, auth error detection (401→MCPAuthExpiredEvent), ext-apps metadata emission, safety annotation registration, and oversized output vault spill (via injectable OversizedResultHandler callback)
- OversizedResultHandler: type alias for the vault-spill callback signature

[POS]
MCP tool discovery layer (not harness Agent runtime). Orchestrates multi-server tool discovery with parallel fetching,
server-prefix isolation (mcp__{server}__{tool} naming), per-server tool filtering
(include/exclude whitelist), description truncation, content block coercion
(file/audio/unknown types gracefully degraded to text for LLM API safety),
content boundary defense (wrap_untrusted for all string outputs against prompt injection),
upstream fault tolerance (catches NotImplementedError/ValueError),
auth error detection (httpx2 401 → MCPAuthExpiredEvent + clear re-auth message),
multimodal result normalization (ImageContent passthrough + structuredContent
extraction), ext-apps UI metadata detection and SSE event emission, and safety
metadata registration. `process_session_tools()` is the single post-processing
chain shared by persistent-session actors and one-shot enumeration.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Sequence

from langchain_core.tools import BaseTool

from myrm_agent_harness.core.security.tool_registry import (
    MCPAnnotations,
    SafetyMetadata,
    register_ptc_safety_metadata,
)

from .client import MCPClientManager, MCPServerConfigProtocol
from .config import (
    parse_mcp_tool_name,
    sanitize_mcp_name_component,
    should_register_mcp_tool,
)
from .schema_utils import (
    FlattenMeta,
    canonicalize_schema_for_cache,
    coerce_arguments_by_schema,
    flatten_deep_schema,
    flatten_json_schema,
    has_dot_keys,
    nest_flat_arguments,
    prepare_mcp_call_arguments,
)

logger = logging.getLogger(__name__)

OversizedResultHandler = Callable[[str, str], str | None]
"""``(content, tool_name) -> summary_with_pointer | None``.

Invoked when an MCP tool result exceeds ``max_output_chars``.  The handler
should persist the full content (e.g. into ArtifactVault) and return a
compact summary containing a retrieval pointer.  Return ``None`` to fall
back to the default head-truncation."""


def _is_mcp_auth_error(exc: Exception) -> bool:
    """Return True if *exc* is an HTTP 401 from the MCP transport layer.

    MCP SDK v2 uses httpx2 internally, so the transport raises
    ``httpx2.HTTPStatusError``.  We also check ``httpx.HTTPStatusError``
    for defensive compatibility (e.g. custom transports that still use httpx).
    """
    status_error_types: list[type] = []
    try:
        from httpx2 import HTTPStatusError as Httpx2StatusError

        status_error_types.append(Httpx2StatusError)
    except ImportError:
        pass
    try:
        from httpx import HTTPStatusError as HttpxStatusError

        status_error_types.append(HttpxStatusError)
    except ImportError:
        pass
    if not status_error_types:
        return False
    return (
        isinstance(exc, tuple(status_error_types)) and exc.response.status_code == 401
    )


def _emit_auth_expired_for_tool(server_name: str, error_detail: str) -> None:
    """Fire MCP auth-expiry notification so the toast/SSE chain can notify the user."""
    from myrm_agent_harness.toolkits.mcp.auth_notify import notify_mcp_auth_expired

    notify_mcp_auth_expired(server_name, error_detail)


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
        filtered = [
            t
            for t in tools
            if should_register_mcp_tool(t.name, tool_include, tool_exclude)
        ]
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
    def _extract_mcp_app_metadata(result: object) -> dict[str, object] | None:
        """Extract MCP Apps (ext-apps) metadata from a tool result.

        Accepts either a ``mcp.types.CallToolResult`` (SDK 2.x native shape) or
        a plain dict.  Returns a dict with ``resource_uri`` and optionally
        ``structured_content`` when the result carries ``_meta.ui.resourceUri``
        (ext-apps standard).
        """
        if result is None:
            return None
        meta = (
            result.get("_meta")
            if isinstance(result, dict)
            else getattr(result, "_meta", None) or getattr(result, "meta", None)
        )
        if not isinstance(meta, dict):
            return None
        ui = meta.get("ui")
        if not isinstance(ui, dict):
            return None
        resource_uri = ui.get("resourceUri")
        if not isinstance(resource_uri, str) or not resource_uri:
            return None
        structured = (
            result.get("structured_content")
            if isinstance(result, dict)
            else getattr(result, "structured_content", None)
        )
        extracted: dict[str, object] = {"resource_uri": resource_uri}
        if structured is not None:
            extracted["structured_content"] = structured
        return extracted

    @staticmethod
    def _coerce_content_block(block: dict[str, object]) -> dict[str, object]:
        """Coerce a LangChain content block to an LLM-safe type.

        MCP tool results may contain ``ResourceLink`` (→ ``{type: "file"}``)
        or ``EmbeddedResource`` blobs that LLM APIs don't accept.  LLM APIs
        (Anthropic, OpenAI) only accept ``text`` and ``image`` in tool results
        — sending ``file`` or unknown types causes 400 errors and permanently
        poisons the session history (every subsequent turn replays the invalid
        block).

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
    def _wrap_multimodal_text_blocks(
        blocks: list[dict[str, object]], *, source: str
    ) -> list[dict[str, object]]:
        """Apply content-boundary defense to text blocks inside multimodal output.

        ``_timeout_wrapper`` wraps plain ``str`` results with ``wrap_untrusted``;
        multimodal ``list[dict]`` results must get the same 5-layer boundary
        treatment on their text blocks, otherwise a malicious MCP server could
        smuggle prompt-injection text next to a legit image and bypass the
        content-boundary defense entirely. Image blocks pass through untouched.
        """
        from myrm_agent_harness.core.security.detection.content_boundary import (
            wrap_untrusted,
        )

        wrapped: list[dict[str, object]] = []
        for block in blocks:
            if block.get("type") == "text":
                text = str(block.get("text", "") or "")
                if text:
                    block = {**block, "text": wrap_untrusted(text, source=source)}
            wrapped.append(block)
        return wrapped

    @staticmethod
    def _normalize_mcp_result(result: object) -> str | list[dict[str, object]]:
        """Normalize an MCP tool execution result for the LLM.

        Accepts either a ``mcp.types.CallToolResult`` (SDK 2.x native shape,
        produced by ``tool_converter._invoke``) or a plain ``str`` (e.g. an
        already-rendered timeout/auth message from ``_timeout_wrapper``).

        CallToolResult handling:
        - ``is_error`` results collapse to a single error ``str`` so the agent
          sees the failure instead of fabricating success (MCP spec: tool-level
          errors are reported inside the result with ``is_error`` so the LLM
          can self-correct).
        - Every ``ContentBlock`` is mapped to a LangChain-style block and passed
          through ``_coerce_content_block`` to guarantee only LLM-safe types
          (``text``, ``image``) reach the API — preventing 400 errors and
          session history poisoning from ``file``, ``audio``, or unknown types.
        - ``structured_content`` is appended as a supplementary JSON text block
          when present.
        - When image blocks survive coercion the full ``list[dict]`` is
          returned so ToolNode can construct a multimodal ``ToolMessage`` that
          flows through the existing streaming pipeline
          (``event_handlers.TOOL_IMAGE_OUTPUT`` → frontend ``ToolImageGallery``);
          otherwise the result is joined into a plain ``str``.
        """
        content_blocks = getattr(result, "content", None)
        if not isinstance(content_blocks, list):
            return str(result)

        is_error = bool(getattr(result, "is_error", False))

        coerced: list[dict[str, object]] = []
        for block in content_blocks:
            if isinstance(block, dict):
                coerced.append(MCPAgent._coerce_content_block(block))
            else:
                coerced.append(MCPAgent._coerce_content_block(MCPAgent._mcp_block_to_lc(block)))

        if is_error:
            error_parts: list[str] = []
            for block in coerced:
                if block.get("type") == "text":
                    text = str(block.get("text", "") or "").strip()
                    if text:
                        error_parts.append(text)
            message = "\n".join(error_parts).strip()
            return f"[MCP tool error] {message}" if message else "[MCP tool error]"

        structured = getattr(result, "structured_content", None)
        if structured is not None:
            coerced.append(
                {"type": "text", "text": json.dumps(structured, ensure_ascii=False)}
            )

        has_image = any(b.get("type") == "image" for b in coerced)
        if has_image:
            return coerced

        texts: list[str] = []
        for block in coerced:
            texts.append(str(block.get("text", "") or ""))
        return "\n".join(texts) if texts else ""

    @staticmethod
    def _mcp_block_to_lc(block: object) -> dict[str, object]:
        """Map an MCP ``ContentBlock`` to a LangChain-style content block dict.

        ``mcp.types.CallToolResult.content`` holds typed block objects
        (``TextContent`` / ``ImageContent`` / ``AudioContent`` /
        ``ResourceLink`` / ``EmbeddedResource``).  This converts them to the
        flat ``{"type": ...}`` shape consumed by ``_coerce_content_block``:
        - ``text`` → ``{"type": "text"}``
        - ``image`` → ``{"type": "image", "base64", "mime_type"}``
        - ``resource_link`` → ``{"type": "file", "url", "mime_type"}``
        - ``resource`` (embedded) → text or image/blob, else file
        - unknown / ``audio`` → degraded ``{"type": "text"}`` marker so the
          LLM still learns the block existed without a huge base64 dump
        """
        block_type = getattr(block, "type", None)

        if block_type == "text":
            return {"type": "text", "text": getattr(block, "text", "") or ""}

        if block_type == "image":
            return {
                "type": "image",
                "base64": getattr(block, "data", "") or "",
                "mime_type": getattr(block, "mime_type", "") or "",
            }

        if block_type == "resource_link":
            return {
                "type": "file",
                "url": getattr(block, "uri", "") or "",
                "mime_type": getattr(block, "mime_type", "") or "",
            }

        if block_type == "resource":
            resource = getattr(block, "resource", None)
            res_text = getattr(resource, "text", None)
            if res_text:
                return {"type": "text", "text": str(res_text)}
            res_blob = getattr(resource, "blob", None)
            mime = getattr(resource, "mime_type", "") or ""
            if res_blob:
                if mime.startswith("image/"):
                    return {"type": "image", "base64": res_blob, "mime_type": mime}
                return {
                    "type": "file",
                    "url": getattr(resource, "uri", "") or "",
                    "mime_type": mime,
                }
            return {
                "type": "file",
                "url": getattr(resource, "uri", "") or "",
                "mime_type": mime,
            }

        if block_type == "audio":
            return {"type": "text", "text": "[audio content omitted]"}

        return {"type": "text", "text": str(block)}

    @staticmethod
    def _handle_oversized_output(
        content: str,
        tool_name: str,
        max_chars: int,
        handler: OversizedResultHandler | None,
    ) -> str:
        """Persist oversized output via *handler*, falling back to head-truncation."""
        original_len = len(content)

        if handler is not None:
            try:
                summary = handler(content, tool_name)
                if summary is not None:
                    logger.info(
                        "MCP tool '%s' output vaulted via handler: %d chars",
                        tool_name,
                        original_len,
                    )
                    return summary
            except Exception:
                logger.warning(
                    "MCP tool '%s' oversized handler failed, falling back to truncation",
                    tool_name,
                    exc_info=True,
                )

        discarded = original_len - max_chars
        logger.warning(
            "MCP tool '%s' output truncated: %d → %d chars",
            tool_name,
            original_len,
            max_chars,
        )
        return (
            f"{content[:max_chars]}\n\n"
            f"[Output truncated: showing first {max_chars:,} of {original_len:,} chars. "
            f"Remaining {discarded:,} chars were discarded to fit context budget.]"
        )

    @staticmethod
    def _wrap_tools_with_timeout(
        tools: list[BaseTool],
        timeout: float,
        max_output_chars: int = 100_000,
        oversized_result_handler: OversizedResultHandler | None = None,
    ) -> None:
        """Wrap MCP tool execution with asyncio.timeout, normalize, and guard output size.

        When *oversized_result_handler* is provided and a tool result exceeds
        *max_output_chars*, the handler is called first to persist the full
        content (e.g. into ArtifactVault).  If the handler returns a summary
        string it replaces the truncated output; if it returns ``None`` or
        raises, the existing head-truncation logic is used as fallback.
        """
        from myrm_agent_harness.core.security.detection.content_boundary import (
            wrap_untrusted,
        )
        from myrm_agent_harness.core.security.redact import redact_sensitive_text

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
                _handler: OversizedResultHandler | None = oversized_result_handler,
                **kwargs: object,
            ) -> str | list[dict[str, object]]:
                try:
                    async with asyncio.timeout(_timeout):
                        raw = await _orig(*args, **kwargs)  # type: ignore[misc]
                        normalized = MCPAgent._normalize_mcp_result(raw)
                        if isinstance(normalized, str) and len(normalized) > _max_chars:
                            normalized = MCPAgent._handle_oversized_output(
                                normalized,
                                _name,
                                _max_chars,
                                _handler,
                            )
                        if isinstance(normalized, str):
                            normalized = wrap_untrusted(
                                normalized, source=f"mcp:{_name}"
                            )
                        else:
                            normalized = MCPAgent._wrap_multimodal_text_blocks(
                                normalized, source=f"mcp:{_name}"
                            )
                except TimeoutError:
                    error_msg = f"MCP tool '{_name}' timed out after {_timeout}s. Server may be slow or unresponsive."
                    logger.error(error_msg)
                    return error_msg
                except (NotImplementedError, ValueError, TypeError) as exc:
                    error_msg = (
                        f"MCP tool '{_name}' returned unsupported content: {exc}"
                    )
                    logger.warning(error_msg)
                    return redact_sensitive_text(error_msg)
                except Exception as exc:
                    if _is_mcp_auth_error(exc):
                        server = parse_mcp_tool_name(_name)
                        srv_label = server[0] if server else _name
                        logger.warning(
                            "MCP tool '%s' failed with auth error (401)", _name
                        )
                        _emit_auth_expired_for_tool(srv_label, str(exc))
                        return (
                            f"MCP server '{srv_label}' requires re-authorization. "
                            f"Ask the user to re-authorize the connection, then ask me to retry."
                        )
                    raise

                # ext-apps emission runs outside the call-timeout budget so a
                # slow progress sink can never turn a healthy tool call into a
                # spurious timeout.
                await MCPAgent._emit_mcp_app_event(raw, _name)
                return normalized

            tool.coroutine = _timeout_wrapper
            # Override response_format to prevent ToolNode from tuple-destructuring
            if hasattr(tool, "response_format"):
                tool.response_format = "content"

    @staticmethod
    async def _emit_mcp_app_event(raw_result: object, tool_name: str) -> None:
        """Emit an MCP_APP_VIEW event if the raw result carries ext-apps UI metadata."""
        mcp_app_meta = MCPAgent._extract_mcp_app_metadata(raw_result)
        if mcp_app_meta is None:
            return
        from myrm_agent_harness.core.events import AgentEventType
        from myrm_agent_harness.utils.runtime.progress_sink import (
            get_tool_progress_sink,
        )

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
            logger.debug(
                "Failed to emit mcp_app event for tool '%s': %s", tool_name, exc
            )

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
                    else (
                        getattr(raw_schema, "model_json_schema", lambda: {})()
                        if raw_schema is not None
                        and hasattr(raw_schema, "model_json_schema")
                        else {}
                    )
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
                    coerced_kwargs = prepare_mcp_call_arguments(coerced_kwargs, _schema)
                    return await _orig(*args, **coerced_kwargs)

                tool.coroutine = _coercion_wrapper

    def _store_tool_server_mapping(
        self, tools: list[BaseTool], server_name: str
    ) -> None:
        """Store tool-to-server name mapping."""
        for tool in tools:
            tool_id = self._get_tool_id(tool)
            self._tool_server_mapping[tool_id] = server_name

    @staticmethod
    def _register_tool_annotations(
        tools: list[BaseTool], server_name: str, host_serial: bool = False
    ) -> None:
        """Extract and register MCP native annotations into PTC safety registry."""
        skill_name = server_name.replace("-", "_").lower()
        if not skill_name.startswith("mcp_"):
            skill_name = f"mcp_{skill_name}"
        if not skill_name.endswith("_skill"):
            skill_name = f"{skill_name}_skill"

        for tool in tools:
            meta = getattr(tool, "metadata", {}) or {}

            annotations: MCPAnnotations = {}
            for key in [
                "readOnlyHint",
                "idempotentHint",
                "destructiveHint",
                "openWorldHint",
            ]:
                if key in meta:
                    annotations[key] = bool(meta[key])  # type: ignore[misc]

            is_read_only = annotations.get("readOnlyHint", False)
            safety_meta = SafetyMetadata(
                is_read_only=is_read_only,
                is_concurrent_safe=is_read_only and not host_serial,
                is_destructive=annotations.get("destructiveHint", False),
                is_open_world=annotations.get("openWorldHint", False),
                is_idempotent=annotations.get("idempotentHint", False),
            )

            register_ptc_safety_metadata(
                skill_name, tool.name, safety_meta, annotations
            )

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
        oversized_result_handler: OversizedResultHandler | None = None,
        host_serial: bool = False,
    ) -> list[BaseTool]:
        """Apply the full post-processing chain to tools bound to a live session.

        Single source of truth shared by the persistent-session actor and the
        one-shot enumeration path, so direct and PTC routes get identical
        filtering, schema sanitization, execution timeout, and safety metadata.
        Returns the filtered, in-place-wrapped tool list (timeout(coercion(call))).

        Pipeline order:
        filter (uses original names) → prefix → description limit →
        sanitize (schema) → timeout + output guard (with optional vault spill) → annotations.
        """
        tools = MCPAgent._apply_tool_filter(
            tools, server_name, tool_include, tool_exclude
        )
        MCPAgent._prefix_tool_names(tools, server_name)
        MCPAgent._enforce_description_limits(tools)
        MCPAgent._sanitize_tools(tools)
        MCPAgent._wrap_tools_with_timeout(
            tools, execute_timeout, max_output_chars, oversized_result_handler
        )
        MCPAgent._register_tool_annotations(tools, server_name, host_serial)
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

    @staticmethod
    def _build_enumeration_target(server_config: MCPServerConfigProtocol) -> object:
        """Build an SDK v2 ``Client`` target for one-shot tool enumeration.

        - SSE: ``sse_client(url, headers=...)`` — SSE transport accepts ``headers``
          directly (no ``http_client`` param).
        - Streamable HTTP with auth headers: ``streamable_http_client(url, http_client=...)``
          — requires an explicit ``httpx2.AsyncClient`` for custom headers.
        - Streamable HTTP without headers: bare URL string (``Client`` auto-wraps).
        - stdio: ``stdio_client(StdioServerParameters(...))`` wrapping.
        """
        raw_target = MCPClientManager.build_client_target(server_config)

        if isinstance(raw_target, str):
            headers = MCPClientManager.get_headers(server_config)
            transport_type = server_config.type
            if transport_type == "sse":
                from mcp.client.sse import sse_client

                return sse_client(raw_target, headers=headers or None)
            if headers:
                import httpx2

                http_client = httpx2.AsyncClient(
                    headers=headers,
                    timeout=httpx2.Timeout(30.0, read=300.0),
                    follow_redirects=True,
                )
                from mcp.client.streamable_http import streamable_http_client

                return streamable_http_client(raw_target, http_client=http_client)
            return raw_target

        from mcp.client.stdio import stdio_client

        return stdio_client(raw_target)

    async def _enumerate_server_tools(
        self,
        server_config: MCPServerConfigProtocol,
    ) -> tuple[str, list[BaseTool], str | None]:
        """Fetch tools from a single MCP server with connection timeout and bounded retry.

        Uses ``mcp.client.Client`` for a one-shot connect→list_tools→disconnect
        cycle.  Transient enumeration failures (empty listing, timeout, connection
        drop) are retried up to ``_TOOL_FETCH_MAX_ATTEMPTS`` times; genuine
        cancellation is never retried.
        """
        from mcp.client import Client
        from mcp.types import Implementation

        from myrm_agent_harness import __version__

        from .tool_converter import convert_mcp_tools

        server_name = server_config.name
        connect_timeout = server_config.connect_timeout
        last_error = "not found tools"

        for attempt in range(1, _TOOL_FETCH_MAX_ATTEMPTS + 1):
            try:
                target = self._build_enumeration_target(server_config)
                client = Client(
                    target,
                    client_info=Implementation(name="myrm-agent", version=__version__),
                )
                async with client:
                    async with asyncio.timeout(connect_timeout):
                        tools = convert_mcp_tools(
                            list((await client.list_tools()).tools),
                            client.call_tool,
                            server_name=server_name,
                        )
                if tools:
                    return server_name, tools, None
                last_error = "not found tools"
            except asyncio.CancelledError as e:
                from .errors import reraise_if_genuine_cancel

                reraise_if_genuine_cancel(e)
                logger.warning("Server %s cancelled by MCP SDK", server_name)
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

    async def get_tools(
        self, mcp_config: Sequence[MCPServerConfigProtocol] | None = None
    ) -> list[BaseTool]:
        """Get all available MCP tools from configured servers.

        Each server gets a one-shot ``mcp.client.Client`` connection for tool
        enumeration.  Multiple servers are fetched in parallel.
        """
        if not mcp_config:
            return []

        self._tool_server_mapping.clear()
        configs = await MCPClientManager.prepare_server_configs(mcp_config)
        if not configs:
            return []

        all_tools: list[BaseTool] = []

        async def _fetch_and_process(cfg: MCPServerConfigProtocol) -> list[BaseTool]:
            server_name, tools, error = await self._enumerate_server_tools(cfg)
            if error:
                raise RuntimeError(f"Failed to get tools from {server_name}: {error}")
            include = getattr(cfg, "tool_include", None)
            exclude = getattr(cfg, "tool_exclude", None)
            tools = self.process_session_tools(
                tools,
                server_name,
                include,
                exclude,
                cfg.execute_timeout,
                getattr(cfg, "max_output_chars", 100_000),
                host_serial=bool(getattr(cfg, "host_serial", False)),
            )
            self._store_tool_server_mapping(tools, server_name)
            return tools

        server_list = list(configs.values())
        if len(server_list) == 1:
            all_tools = await _fetch_and_process(server_list[0])
        else:
            results = await asyncio.gather(
                *[_fetch_and_process(cfg) for cfg in server_list],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.error("MCP server fetch failed: %s", result)
                    raise result
                all_tools.extend(result)

        return all_tools
