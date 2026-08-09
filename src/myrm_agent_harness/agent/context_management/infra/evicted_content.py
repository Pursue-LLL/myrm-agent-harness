"""Unified evicted content delivery — persist, cap, footer, and GUI ref contract.

All large tool/web outputs that spill to disk use `.context/{session_id}/evicted/`
with `{source}_{hex8}.{ext}` basenames so the product evicted-file API and drawer
work consistently across bash, web_fetch, MCP, and FilterProcessor backup paths.

[INPUT]
- core.context_vars::workspace_root_var, chat_id_var
- infra.atomic_write::async_atomic_write

[OUTPUT]
- cap_content_for_storage, build_evicted_basename, build_delivery_footer
- persist_evicted_content, write_evicted_content_sync, emit_evicted_ref
- EvictedRefPayload, EvictedPersistResult, EVICTED_BASENAME_PATTERN
- normalize_delivery_chat_id

[POS]
SSOT for sandbox evicted content delivery (agent context_management infra).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.core.context_vars import chat_id_var, workspace_root_var
from myrm_agent_harness.infra.atomic_write import async_atomic_write

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

MAX_STORED_CHARS = 2_000_000
MAX_PREVIEW_STDOUT_CHARS = 8_000
_TRUNCATION_MARKER_TEMPLATE = (
    "\n\n[... stored copy truncated at {cap:,} chars of {original:,}; "
    "re-fetch or read a narrower URL for the remainder ...]"
)

_SOURCE_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_SOURCE_LEN = 32
_ALLOWED_EXTENSIONS = frozenset({"txt", "md", "log", "json"})
_ALLOWED_SOURCE_PREFIXES = frozenset({"output", "web_fetch", "mcp", "tool", "filter"})

# Keep in sync with myrm-agent-server app/api/files/evicted.py (_FILENAME_PATTERN imports this).
EVICTED_BASENAME_PATTERN = re.compile(
    r"^(?:output|web_fetch|mcp|tool|filter)_[a-f0-9]{8}\.(?:txt|md|log|json)$"
)


@dataclass(frozen=True, slots=True)
class EvictedRefPayload:
    """Structured GUI binding contract for tool_evicted_ref custom events."""

    evicted_ref: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    preview_stdout: str | None = None
    stored_chars: int | None = None
    total_lines: int | None = None
    storage_truncated: bool = False

    def to_event_dict(self) -> dict[str, str | int | bool]:
        payload: dict[str, str | int | bool] = {"evicted_ref": self.evicted_ref}
        if self.tool_name:
            payload["tool_name"] = self.tool_name
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.preview_stdout:
            payload["preview_stdout"] = self.preview_stdout
        if self.stored_chars is not None and self.stored_chars > 0:
            payload["stored_chars"] = self.stored_chars
        if self.total_lines is not None and self.total_lines > 0:
            payload["total_lines"] = self.total_lines
        if self.storage_truncated:
            payload["storage_truncated"] = True
        return payload


@dataclass(frozen=True, slots=True)
class EvictedPersistResult:
    """Result of persisting content to the evicted directory."""

    evicted_ref: str | None
    rel_path: str | None
    stored_chars: int
    total_lines: int = 0
    storage_truncated: bool = False


def cap_content_for_storage(
    content: str, *, max_chars: int = MAX_STORED_CHARS
) -> tuple[str, bool]:
    """Cap content before writing to Volume; returns (text, was_truncated)."""
    if len(content) <= max_chars:
        return content, False
    capped = content[:max_chars] + _TRUNCATION_MARKER_TEMPLATE.format(
        cap=max_chars,
        original=len(content),
    )
    return capped, True


def sanitize_evicted_source(source: str) -> str:
    """Normalize a source label into a safe filename prefix."""
    cleaned = _SOURCE_SANITIZE_RE.sub("_", source.strip().lower())
    cleaned = cleaned.strip("_") or "tool"
    if len(cleaned) > _MAX_SOURCE_LEN:
        cleaned = cleaned[:_MAX_SOURCE_LEN].rstrip("_")
    if cleaned not in _ALLOWED_SOURCE_PREFIXES:
        return "tool"
    return cleaned or "tool"


def build_evicted_basename(source: str, *, ext: str = "txt") -> str:
    """Build a drawer-safe evicted filename basename."""
    safe_ext = ext.lower().lstrip(".")
    if safe_ext not in _ALLOWED_EXTENSIONS:
        safe_ext = "txt"
    prefix = sanitize_evicted_source(source)
    return f"{prefix}_{uuid.uuid4().hex[:8]}.{safe_ext}"


def build_delivery_footer(
    *,
    evicted_basename: str,
    head_text: str | None = None,
    rel_path: str | None = None,
) -> str:
    """Actionable footer telling the model how to read omitted content.

    Emits a valid ``file_read_tool(paths=[...])`` line-range instruction. When
    ``start_line`` is unknown (e.g. structural summaries with no line mapping),
    the footer falls back to a plain full-file read so the model is never
    pointed at a misleading offset.
    """
    start_line = _footer_start_line(head_text)
    path_hint = rel_path if rel_path else f".context/.../evicted/{evicted_basename}"
    if start_line is not None:
        read_cmd = f'file_read_tool(paths=["{path_hint}:{start_line}-"])'
    else:
        read_cmd = f'file_read_tool(paths=["{path_hint}"])'
    return (
        f"\n\nFull content saved to sandbox storage: {path_hint}\n"
        f"Use {read_cmd} to read omitted sections. GUI users can open View full output."
    )


def _footer_start_line(head_text: str | None) -> int | None:
    """Estimate the first omitted line (1-indexed) from the previewed head.

    Returns ``None`` when the head cannot be mapped to source line numbers:
    empty preview, structural summary without line correspondence, or a
    single-line head (line-range reads are meaningless for one-line files —
    a ``:N-`` instruction would point past the only line and read nothing).
    """
    if not head_text:
        return None
    newlines = head_text.count("\n")
    if newlines == 0:
        return None
    if head_text.endswith("\n"):
        return newlines + 1
    return newlines + 2


def normalize_delivery_chat_id(raw: str) -> str:
    """Map approval session keys (`chat_{id}`) to API/UI chat ids."""
    chat_id = raw.strip()
    if chat_id.startswith("chat_"):
        return chat_id.removeprefix("chat_")
    return chat_id


def _resolve_persist_target(source: str, ext: str) -> tuple[str, str, Path] | None:
    workspace_root = workspace_root_var.get().strip()
    chat_id = normalize_delivery_chat_id(chat_id_var.get())
    if not workspace_root or not chat_id:
        logger.warning(
            "[EvictedContent] Missing workspace_root or chat_id, skip persist"
        )
        return None
    basename = build_evicted_basename(source, ext=ext)
    rel_dir = Path(".context") / chat_id / "evicted"
    rel_path = str(rel_dir / basename)
    abs_path = Path(workspace_root) / rel_path
    return basename, rel_path, abs_path


def write_evicted_content_sync(
    content: str,
    source: str,
    *,
    ext: str = "txt",
) -> EvictedPersistResult:
    """Sync persist helper for callers that cannot await."""
    target = _resolve_persist_target(source, ext)
    if target is None:
        return EvictedPersistResult(evicted_ref=None, rel_path=None, stored_chars=0)

    basename, rel_path, abs_path = target
    capped, storage_truncated = cap_content_for_storage(content)
    from myrm_agent_harness.agent.context_management.infra.evicted_reader import (
        count_lines_in_text,
    )

    total_lines = count_lines_in_text(capped)

    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(capped, encoding="utf-8")
        logger.info("[EvictedContent] Saved %d chars to %s", len(capped), rel_path)
        return EvictedPersistResult(
            evicted_ref=basename,
            rel_path=rel_path,
            stored_chars=len(capped),
            total_lines=total_lines,
            storage_truncated=storage_truncated,
        )
    except OSError as exc:
        logger.warning("[EvictedContent] Failed to persist: %s", exc)
        return EvictedPersistResult(evicted_ref=None, rel_path=None, stored_chars=0)


async def persist_evicted_content(
    content: str,
    source: str,
    *,
    ext: str = "txt",
) -> EvictedPersistResult:
    """Persist capped content under `.context/{chat_id}/evicted/`."""
    target = _resolve_persist_target(source, ext)
    if target is None:
        return EvictedPersistResult(evicted_ref=None, rel_path=None, stored_chars=0)

    basename, rel_path, abs_path = target
    capped, storage_truncated = cap_content_for_storage(content)
    from myrm_agent_harness.agent.context_management.infra.evicted_reader import (
        count_lines_in_text,
    )

    total_lines = count_lines_in_text(capped)

    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        await async_atomic_write(abs_path, capped)
        logger.info("[EvictedContent] Saved %d chars to %s", len(capped), rel_path)
        return EvictedPersistResult(
            evicted_ref=basename,
            rel_path=rel_path,
            stored_chars=len(capped),
            total_lines=total_lines,
            storage_truncated=storage_truncated,
        )
    except OSError as exc:
        logger.warning("[EvictedContent] Failed to persist: %s", exc)
        return EvictedPersistResult(evicted_ref=None, rel_path=None, stored_chars=0)


def build_evicted_ref_payload(
    evicted_ref: str,
    *,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    preview_stdout: str | None = None,
    stored_chars: int | None = None,
    total_lines: int | None = None,
    storage_truncated: bool = False,
    config: RunnableConfig | None = None,
) -> EvictedRefPayload:
    """Build the SSOT payload for tool_evicted_ref SSE/DB binding."""
    from myrm_agent_harness.utils.event_utils import resolve_tool_call_id_from_config

    resolved_tool_call_id = tool_call_id or resolve_tool_call_id_from_config(config)
    preview = preview_stdout
    if preview and len(preview) > MAX_PREVIEW_STDOUT_CHARS:
        preview = preview[:MAX_PREVIEW_STDOUT_CHARS]
    return EvictedRefPayload(
        evicted_ref=evicted_ref,
        tool_name=tool_name,
        tool_call_id=resolved_tool_call_id,
        preview_stdout=preview,
        stored_chars=stored_chars,
        total_lines=total_lines,
        storage_truncated=storage_truncated,
    )


async def emit_evicted_ref(
    evicted_ref: str,
    *,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    preview_stdout: str | None = None,
    stored_chars: int | None = None,
    total_lines: int | None = None,
    storage_truncated: bool = False,
    config: RunnableConfig | None = None,
) -> None:
    """Notify the GUI that full content is available in the evicted drawer."""
    from myrm_agent_harness.utils.event_utils import dispatch_custom_event

    payload = build_evicted_ref_payload(
        evicted_ref,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        preview_stdout=preview_stdout,
        stored_chars=stored_chars,
        total_lines=total_lines,
        storage_truncated=storage_truncated,
        config=config,
    )
    event_payload = payload.to_event_dict()
    if config is not None:
        await dispatch_custom_event("tool_evicted_ref", event_payload, config=config)
    else:
        await dispatch_custom_event("tool_evicted_ref", event_payload)
