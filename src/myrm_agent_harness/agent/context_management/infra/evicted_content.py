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
- EvictedPersistResult, EVICTED_BASENAME_PATTERN

[POS]
SSOT for sandbox evicted content delivery (agent context_management infra).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.core.context_vars import chat_id_var, workspace_root_var
from myrm_agent_harness.infra.atomic_write import async_atomic_write

logger = logging.getLogger(__name__)

MAX_STORED_CHARS = 2_000_000
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
class EvictedPersistResult:
    """Result of persisting content to the evicted directory."""

    evicted_ref: str | None
    rel_path: str | None
    stored_chars: int
    storage_truncated: bool = False


def cap_content_for_storage(content: str, *, max_chars: int = MAX_STORED_CHARS) -> tuple[str, bool]:
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
    head_text: str,
    rel_path: str | None = None,
    read_limit: int = 200,
) -> str:
    """Actionable footer telling the model how to read omitted content."""
    middle_start_line = head_text.count("\n") + 2
    path_hint = rel_path if rel_path else f".context/.../evicted/{evicted_basename}"
    return (
        f"\n\nFull content saved to sandbox storage: {path_hint}\n"
        f'Use file_read_tool path="{path_hint}" offset={middle_start_line} limit={read_limit} '
        f"to read omitted sections. GUI users can open View full output."
    )


def _resolve_persist_target(source: str, ext: str) -> tuple[str, str, Path] | None:
    workspace_root = workspace_root_var.get().strip()
    chat_id = chat_id_var.get().strip()
    if not workspace_root or not chat_id:
        logger.warning("[EvictedContent] Missing workspace_root or chat_id, skip persist")
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

    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(capped, encoding="utf-8")
        logger.info("[EvictedContent] Saved %d chars to %s", len(capped), rel_path)
        return EvictedPersistResult(
            evicted_ref=basename,
            rel_path=rel_path,
            stored_chars=len(capped),
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

    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        await async_atomic_write(abs_path, capped)
        logger.info("[EvictedContent] Saved %d chars to %s", len(capped), rel_path)
        return EvictedPersistResult(
            evicted_ref=basename,
            rel_path=rel_path,
            stored_chars=len(capped),
            storage_truncated=storage_truncated,
        )
    except OSError as exc:
        logger.warning("[EvictedContent] Failed to persist: %s", exc)
        return EvictedPersistResult(evicted_ref=None, rel_path=None, stored_chars=0)


async def emit_evicted_ref(evicted_basename: str) -> None:
    """Notify the GUI that full content is available in the evicted drawer."""
    from myrm_agent_harness.utils.event_utils import dispatch_custom_event

    await dispatch_custom_event(
        "tool_evicted_ref",
        {"evicted_ref": evicted_basename},
    )
