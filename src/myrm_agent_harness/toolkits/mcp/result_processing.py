"""MCP tool result normalization — pure functions over MCP call results.

Sibling of ``agent.py``: keeps ``MCPAgent`` as the orchestration facade while
the LLM-facing result pipeline (coercion, boundary defense, size guard,
ext-apps metadata) lives here as stateless module-level functions.

[INPUT]
- core.security.detection.content_boundary::wrap_untrusted (POS: 5-layer content boundary defense for MCP tool outputs)
- core.events::AgentEventType (POS: Framework-agnostic streaming event types)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: Runtime tool progress event sink)
- config::parse_mcp_tool_name (POS: MCP configuration, name sanitization, tool name parsing, and per-server tool filter function)

[OUTPUT]
- OversizedResultHandler: callback type for vault-spilling oversized MCP tool outputs
- normalize_mcp_result, coerce_content_block, mcp_block_to_lc
- wrap_multimodal_text_blocks, truncate_multimodal_text_blocks, handle_oversized_output
- extract_mcp_app_metadata, emit_mcp_app_event

[POS]
MCP tool result normalization. Collapses ``is_error`` results (including
SEP-2145 ``structured_content`` error details), coerces every content block to
LLM-safe ``text``/``image`` types, applies the output-size guard and content
boundary defense per text block, and detects ext-apps UI metadata for SSE
emission. No agent/runtime coupling — invoked by ``MCPAgent``'s timeout wrapper.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

OversizedResultHandler = Callable[[str, str], str | None]
"""``(content, tool_name) -> summary_with_pointer | None``.

Invoked when an MCP tool result exceeds ``max_output_chars``.  The handler
should persist the full content (e.g. into ArtifactVault) and return a
compact summary containing a retrieval pointer.  Return ``None`` to fall
back to the default head-truncation."""


def _mime_type(block: object) -> str:
    """Read a MIME type from an MCP content block or its dict form.

    MCP SDK 2.x typed blocks expose the snake_case field ``mime_type``, while
    wire-serialized dicts carry camelCase ``mimeType``.  Tolerate both shapes
    so image/resource handling works on either input.
    """
    if isinstance(block, dict):
        return str(block.get("mimeType") or block.get("mime_type") or "")
    return str(getattr(block, "mime_type", None) or "")


def coerce_content_block(block: dict[str, object]) -> dict[str, object]:
    """Coerce a LangChain content block to an LLM-safe type.

    MCP tool results may contain ``ResourceLink`` (→ ``{type: "file"}``)
    or ``EmbeddedResource`` blobs that LLM APIs don't accept.  LLM APIs
    (Anthropic, OpenAI) only accept ``text`` and ``image`` in tool results
    — sending ``file`` or unknown types causes 400 errors and permanently
    poisons the session history (every subsequent turn replays the invalid
    block).

    This acts as a safety boundary: ``text`` and well-formed ``image``
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
        mime = _mime_type(block)
        label = f"[file: {url}]" if url else f"[file {mime}]"
        logger.warning("Degrading file block to text: %s", label)
        return {"type": "text", "text": label}

    logger.warning("Degrading unknown content block type '%s' to text", block_type)
    return {"type": "text", "text": json.dumps(block, default=str)}


def mcp_block_to_lc(block: object) -> dict[str, object]:
    """Map an MCP ``ContentBlock`` to a LangChain-style content block dict.

    ``mcp.types.CallToolResult.content`` holds typed block objects
    (``TextContent`` / ``ImageContent`` / ``AudioContent`` /
    ``ResourceLink`` / ``EmbeddedResource``).  This converts them to the
    flat ``{"type": ...}`` shape consumed by ``coerce_content_block``:
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
            "mime_type": _mime_type(block),
        }

    if block_type == "resource_link":
        return {
            "type": "file",
            "url": getattr(block, "uri", "") or "",
            "mime_type": _mime_type(block),
        }

    if block_type == "resource":
        resource = getattr(block, "resource", None)
        res_text = getattr(resource, "text", None)
        if res_text:
            return {"type": "text", "text": str(res_text)}
        res_blob = getattr(resource, "blob", None)
        mime = _mime_type(resource)
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


def normalize_mcp_result(result: object) -> str | list[dict[str, object]]:
    """Normalize an MCP tool execution result for the LLM.

    Accepts either a ``mcp.types.CallToolResult`` (SDK 2.x native shape,
    produced by ``tool_converter._invoke``) or a plain ``str`` (e.g. an
    already-rendered timeout/auth message from the caller).

    CallToolResult handling:
    - ``is_error`` results collapse to a single error ``str`` so the agent
      sees the failure instead of fabricating success (MCP spec: tool-level
      errors are reported inside the result with ``is_error`` so the LLM
      can self-correct). Error details carried in ``structured_content``
      (SEP-2145 errorSchema envelope) are appended when not already present
      in the joined text blocks.
    - Every ``ContentBlock`` is mapped to a LangChain-style block and passed
      through ``coerce_content_block`` to guarantee only LLM-safe types
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

    is_error = bool(getattr(result, "is_error", None))
    structured = getattr(result, "structured_content", None)

    coerced: list[dict[str, object]] = []
    for block in content_blocks:
        if isinstance(block, dict):
            coerced.append(coerce_content_block(block))
        else:
            coerced.append(coerce_content_block(mcp_block_to_lc(block)))

    if is_error:
        error_parts: list[str] = []
        for block in coerced:
            if block.get("type") == "text":
                text = str(block.get("text", "") or "").strip()
                if text:
                    error_parts.append(text)
        message = "\n".join(error_parts).strip()
        # Error details may live in structured_content (SEP-2145: errorSchema
        # envelope) instead of a text block. Surface them too so the LLM can
        # self-correct instead of seeing a bare error marker. Dedup against
        # already-joined text since the spec suggests servers mirror the
        # serialized JSON in a TextContent block.
        if structured is not None:
            try:
                serialized = json.dumps(structured, ensure_ascii=False)
            except (TypeError, ValueError):
                serialized = ""
            if serialized and serialized not in message:
                message = f"{message}\n{serialized}" if message else serialized
        return f"[MCP tool error] {message}" if message else "[MCP tool error]"

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


def wrap_multimodal_text_blocks(
    blocks: list[dict[str, object]], *, source: str
) -> list[dict[str, object]]:
    """Apply content-boundary defense to text blocks inside multimodal output.

    Plain ``str`` results are wrapped with ``wrap_untrusted``; multimodal
    ``list[dict]`` results must get the same 5-layer boundary treatment on
    their text blocks, otherwise a malicious MCP server could smuggle
    prompt-injection text next to a legit image and bypass the content-boundary
    defense entirely. Image blocks pass through untouched.
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


def truncate_multimodal_text_blocks(
    blocks: list[dict[str, object]],
    tool_name: str,
    max_chars: int,
    handler: OversizedResultHandler | None,
) -> list[dict[str, object]]:
    """Apply the output-size guard to text blocks inside multimodal output.

    Plain ``str`` results that exceed ``max_output_chars`` are truncated;
    multimodal ``list[dict]`` results must apply the same guard to each text
    block so a malicious or defective MCP server cannot bypass the context
    budget by pairing a huge text block with a legitimate image.  Image blocks
    pass through untouched — the vault spill / head-truncation falls back to
    ``handle_oversized_output``.
    """
    truncated: list[dict[str, object]] = []
    for block in blocks:
        if block.get("type") == "text":
            text = str(block.get("text", "") or "")
            if len(text) > max_chars:
                text = handle_oversized_output(text, tool_name, max_chars, handler)
                block = {**block, "text": text}
        truncated.append(block)
    return truncated


def handle_oversized_output(
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


def extract_mcp_app_metadata(result: object) -> dict[str, object] | None:
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
        else getattr(result, "meta", None)
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


async def emit_mcp_app_event(raw_result: object, tool_name: str) -> None:
    """Emit an MCP_APP_VIEW event if the raw result carries ext-apps UI metadata."""
    mcp_app_meta = extract_mcp_app_metadata(raw_result)
    if mcp_app_meta is None:
        return
    from myrm_agent_harness.core.events import AgentEventType
    from myrm_agent_harness.utils.runtime.progress_sink import (
        get_tool_progress_sink,
    )

    sink = get_tool_progress_sink()
    if sink is None:
        return
    from .config import parse_mcp_tool_name

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
