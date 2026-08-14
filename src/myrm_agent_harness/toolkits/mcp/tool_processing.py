"""MCP tool post-processing — pure functions over LangChain tool objects.

Sibling of ``agent.py``: keeps ``MCPAgent`` as the orchestration facade while
the per-tool pipeline stages (filtering, description limits, schema
sanitization, safety annotations, name prefixing) live here as stateless
module-level functions.

[INPUT]
- config::sanitize_mcp_name_component, should_register_mcp_tool (POS: MCP configuration, name sanitization, tool name parsing, and per-server tool filter function)
- schema::FlattenMeta, canonicalize_schema_for_cache, flatten_deep_schema, flatten_json_schema, has_dot_keys, nest_flat_arguments, coerce_arguments_by_schema, prepare_mcp_call_arguments (POS: MCP inbound tool schema normalization)
- core.security.tool_registry::MCPAnnotations, SafetyMetadata, register_ptc_safety_metadata (POS: Tool metadata and permission mapping)

[OUTPUT]
- apply_tool_filter, enforce_description_limits, sanitize_tools, register_tool_annotations, prefix_tool_names
- wrap_tools_with_timeout (with auth-error detection + MCPAuthExpiredEvent notification)

[POS]
MCP tool post-processing. Applies config-time least-privilege filtering, caps
overlong descriptions for token economy, sanitizes argument schemas
($ref→canonicalize→flatten→coerce→nest), registers MCP native annotations into
the PTC safety registry, prefixes names with ``mcp__{server}__`` for collision
and permission-bypass isolation, and wraps execution with timeout, result
normalization, content boundary defense, and oversized-output guarding. No
agent/runtime coupling — invoked by ``MCPAgent.process_session_tools``.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.tools import BaseTool

from myrm_agent_harness.core.security.tool_registry import (
    MCPAnnotations,
    SafetyMetadata,
    register_ptc_safety_metadata,
)

from .config import (
    parse_mcp_tool_name,
    sanitize_mcp_name_component,
    should_register_mcp_tool,
)
from .result_processing import (
    OversizedResultHandler,
    emit_mcp_app_event,
    handle_oversized_output,
    normalize_mcp_result,
    truncate_multimodal_text_blocks,
    wrap_multimodal_text_blocks,
)
from .schema import (
    FlattenMeta,
    canonicalize_schema_for_cache,
    coerce_arguments_by_schema,
    flatten_deep_schema,
    flatten_json_schema,
    has_dot_keys,
    nest_flat_arguments,
    prepare_mcp_call_arguments,
)
from .schema.key_sanitize import restore_property_keys, sanitize_property_keys

logger = logging.getLogger(__name__)

# Auto-generated MCP servers (e.g. Swagger/OpenAPI converters) may embed
# 15-60 KB of API docs into tool descriptions, wasting massive tokens.
# 2048 chars ≈ 512 tokens — sufficient for core descriptions while
# capping 50 tools at ~25K tokens (vs. 750K+ without truncation).
_MAX_MCP_TOOL_DESCRIPTION_LEN = 2048


def apply_tool_filter(
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


def enforce_description_limits(tools: list[BaseTool]) -> None:
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


def sanitize_tools(tools: list[BaseTool]) -> None:
    """Sanitize tool schemas: $ref resolution -> canonicalize -> key sanitize -> deep-flatten -> coerce -> nest.

    Full error-tolerance chain for MCP tool parameters:
    1. Resolve $ref pointers inline
    2. Canonicalize key ordering for prompt prefix cache stability
    3. Rename non-conforming property keys (provider key-pattern compat);
       the reverse map rides on ``tool.metadata`` so dispatch can restore
       the original wire names before the MCP call
    4. Flatten deeply-nested schemas to dot-path notation (for LLM compatibility)
    5. Wrap execution with type coercion + argument nesting restoration +
       wire-name restoration
    """
    for tool in tools:
        flatten_meta = FlattenMeta(was_flattened=False)
        # A tool may pass through ``sanitize_tools`` more than once (e.g. a
        # cached object re-processed by a later session). Once keys are
        # renamed the second pass finds nothing new, so fall back to the
        # restore map already stored on ``metadata`` — otherwise the fresh
        # wrapper would silently drop wire-name restoration.
        meta = getattr(tool, "metadata", {}) or {}
        restore_map = meta.get("_key_restore_map", {}) if isinstance(meta.get("_key_restore_map"), dict) else {}

        if hasattr(tool, "args_schema") and isinstance(tool.args_schema, dict):
            # Step 1: Resolve $ref pointers
            tool.args_schema = flatten_json_schema(tool.args_schema)
            # Step 2: Canonicalize key ordering for prefix cache stability
            tool.args_schema = canonicalize_schema_for_cache(tool.args_schema)  # type: ignore[assignment]
            # Step 3: Rename non-conforming property keys (runs before
            # flattening so the rename never interacts with the dot-path
            # separator used by ``nest_flat_arguments``).
            sanitized, new_renames = sanitize_property_keys(tool.args_schema)
            if new_renames:
                restore_map = {**restore_map, **new_renames}
                meta = getattr(tool, "metadata", {}) or {}
                tool.metadata = {**meta, "_key_restore_map": restore_map}
            tool.args_schema = sanitized
            # Step 4: Flatten deep nesting to dot-path notation
            tool.args_schema, flatten_meta = flatten_deep_schema(tool.args_schema)

        # Step 5: Wrap execution with type coercion + argument nesting
        original_coroutine = getattr(tool, "coroutine", None)
        if original_coroutine:
            raw_schema = getattr(tool, "args_schema", None)
            schema_for_coercion = (
                raw_schema
                if isinstance(raw_schema, dict)
                else (
                    getattr(raw_schema, "model_json_schema", lambda: {})()
                    if raw_schema is not None and hasattr(raw_schema, "model_json_schema")
                    else {}
                )
            )

            async def _coercion_wrapper(
                *args,
                _orig=original_coroutine,
                _schema=schema_for_coercion,
                _meta=flatten_meta,
                _restore=restore_map,
                **kwargs,
            ):
                coerced_kwargs = coerce_arguments_by_schema(_schema, kwargs)
                # Restore nested structure only if schema was flattened AND model used dot-keys
                if _meta.was_flattened and has_dot_keys(coerced_kwargs):
                    coerced_kwargs = nest_flat_arguments(coerced_kwargs)
                coerced_kwargs = prepare_mcp_call_arguments(coerced_kwargs, _schema)
                if _restore:
                    coerced_kwargs = restore_property_keys(coerced_kwargs, _restore)
                return await _orig(*args, **coerced_kwargs)

            tool.coroutine = _coercion_wrapper


def register_tool_annotations(tools: list[BaseTool], server_name: str, host_serial: bool = False) -> None:
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

        register_ptc_safety_metadata(skill_name, tool.name, safety_meta, annotations)


def prefix_tool_names(tools: list[BaseTool], server_name: str) -> None:
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
    return isinstance(exc, tuple(status_error_types)) and exc.response.status_code == 401


def _emit_auth_expired_for_tool(server_name: str, error_detail: str) -> None:
    """Fire MCP auth-expiry notification so the toast/SSE chain can notify the user."""
    from myrm_agent_harness.toolkits.mcp.auth_notify import notify_mcp_auth_expired

    notify_mcp_auth_expired(server_name, error_detail)


def wrap_tools_with_timeout(
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
                    normalized = normalize_mcp_result(raw)
                    if isinstance(normalized, str):
                        if len(normalized) > _max_chars:
                            normalized = handle_oversized_output(
                                normalized,
                                _name,
                                _max_chars,
                                _handler,
                            )
                        normalized = wrap_untrusted(normalized, source=f"mcp:{_name}")
                    else:
                        # Multimodal text blocks get the same output-size guard
                        # as plain-string results first, then the content
                        # boundary — a malicious/oversized server must not
                        # bypass max_output_chars by pairing a huge text
                        # block with a legitimate image.  Truncating before
                        # wrapping keeps the UNTRUSTED_DATA markers intact.
                        normalized = truncate_multimodal_text_blocks(normalized, _name, _max_chars, _handler)
                        normalized = wrap_multimodal_text_blocks(normalized, source=f"mcp:{_name}")
            except TimeoutError:
                error_msg = f"MCP tool '{_name}' timed out after {_timeout}s. Server may be slow or unresponsive."
                logger.error(error_msg)
                return error_msg
            except (NotImplementedError, ValueError, TypeError) as exc:
                error_msg = f"MCP tool '{_name}' returned unsupported content: {exc}"
                logger.warning(error_msg)
                return redact_sensitive_text(error_msg)
            except Exception as exc:
                if _is_mcp_auth_error(exc):
                    server = parse_mcp_tool_name(_name)
                    srv_label = server[0] if server else _name
                    logger.warning("MCP tool '%s' failed with auth error (401)", _name)
                    _emit_auth_expired_for_tool(srv_label, str(exc))
                    return (
                        f"MCP server '{srv_label}' requires re-authorization. "
                        f"Ask the user to re-authorize the connection, then ask me to retry."
                    )
                raise

            # ext-apps emission runs outside the call-timeout budget so a
            # slow progress sink can never turn a healthy tool call into a
            # spurious timeout.
            await emit_mcp_app_event(raw, _name)
            return normalized

        tool.coroutine = _timeout_wrapper
        # Override response_format to prevent ToolNode from tuple-destructuring
        if hasattr(tool, "response_format"):
            tool.response_format = "content"
