"""Context archive reference data model.

[INPUT]
- dataclasses::dataclass (POS: Python standard dataclass support)
- pathlib::PurePosixPath (POS: platform-neutral path parsing)

[OUTPUT]
- ContextArchiveReference: Structured reference for archived context payloads.
- build_tool_result_archive_reference: Build a stable tool-result archive reference.
- extract_context_archive_session_id: Extract session id from compacted context paths.
- is_context_archive_path: Detect compacted context archive paths.
- is_context_archive_path_for_session: Detect whether an archive path belongs to a session.

[POS]
Structured archive references for offloaded context payloads. Keeps prompt text
recoverable while exposing stable fields for metrics, health, telemetry, and
session-scoped restore guards.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

ArchiveReason = Literal["cache_ttl_expired"]
ArchiveReferenceType = Literal["tool_result"]
ArchiveContentType = Literal["text", "json", "unknown"]
RestoreTool = Literal["file_read_tool"]


@dataclass(frozen=True, slots=True)
class ContextArchiveReference:
    """Structured reference for an offloaded context payload."""

    version: int
    reference_type: ArchiveReferenceType
    archive_id: str
    archive_path: str
    session_id: str
    tool_name: str
    content_type: ArchiveContentType
    content_sha256: str
    original_tokens: int
    original_chars: int
    content_index: dict[str, object]
    reason: ArchiveReason
    restore_tool: RestoreTool
    restore_args: dict[str, str]
    chunk_restore_args: list[dict[str, str]]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "reference_type": self.reference_type,
            "archive_id": self.archive_id,
            "archive_path": self.archive_path,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "content_type": self.content_type,
            "content_sha256": self.content_sha256,
            "original_tokens": self.original_tokens,
            "original_chars": self.original_chars,
            "content_index": self.content_index,
            "reason": self.reason,
            "restore_tool": self.restore_tool,
            "restore_args": self.restore_args,
            "chunk_restore_args": self.chunk_restore_args,
        }

    def render_for_model(self) -> str:
        """Render a compact model-readable restore hint."""
        payload = json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
        return (
            "[Tool result archived after prompt cache TTL expiry]\n"
            f"- archive_ref: {payload}\n"
            f"- archived_path: {self.archive_path}\n"
            f"- restore_tool: {self.restore_tool}\n"
            f"- original_tokens: {self.original_tokens}\n"
            f"- original_chars: {self.original_chars}\n"
            "- restore: call restore_tool with restore_args when exact archived details are needed."
        )


def build_tool_result_archive_reference(
    *,
    tool_name: str,
    archive_path: str,
    content: str,
    original_tokens: int,
    original_chars: int,
    reason: ArchiveReason = "cache_ttl_expired",
) -> ContextArchiveReference:
    """Build a deterministic archive reference for a tool result."""
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    digest_source = f"{tool_name}\0{archive_path}\0{original_tokens}\0{original_chars}\0{content_sha256}"
    archive_id = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]
    session_id = extract_context_archive_session_id(archive_path) or ""
    return ContextArchiveReference(
        version=1,
        reference_type="tool_result",
        archive_id=archive_id,
        archive_path=archive_path,
        session_id=session_id,
        tool_name=tool_name,
        content_type=_detect_content_type(content),
        content_sha256=content_sha256,
        original_tokens=original_tokens,
        original_chars=original_chars,
        content_index=_build_content_index(content),
        reason=reason,
        restore_tool="file_read_tool",
        restore_args={"path": archive_path},
        chunk_restore_args=_build_chunk_restore_args(archive_path, content),
    )


def _detect_content_type(content: str) -> ArchiveContentType:
    stripped = content.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(content)
        except json.JSONDecodeError:
            return "text"
        return "json"
    if content:
        return "text"
    return "unknown"


def _build_content_index(content: str) -> dict[str, object]:
    """Build a lightweight structural index without copying archive content."""
    lines = content.splitlines()
    line_count = len(lines)
    chunk_size = 200
    chunk_count = (line_count + chunk_size - 1) // chunk_size if line_count > 0 else 0
    chunk_ranges = [
        {"start_line": start + 1, "end_line": min(start + chunk_size, line_count)}
        for start in range(0, min(line_count, chunk_size * 12), chunk_size)
    ]
    index: dict[str, object] = {
        "line_count": line_count,
        "chunk_size_lines": chunk_size,
        "chunk_count": chunk_count,
        "chunk_ranges": chunk_ranges,
    }
    headings = _markdown_heading_index(lines)
    if headings:
        index["markdown_headings"] = headings
    code_blocks = _code_block_ranges(lines)
    if code_blocks:
        index["code_block_ranges"] = code_blocks
    table_ranges = _table_ranges(lines)
    if table_ranges:
        index["table_ranges"] = table_ranges
    list_ranges = _list_item_ranges(lines)
    if list_ranges:
        index["list_item_ranges"] = list_ranges

    stripped = content.lstrip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return index
        if isinstance(parsed, dict):
            index["json_top_level_keys"] = [str(key) for key in list(parsed.keys())[:50]]
        elif isinstance(parsed, list):
            index["json_array_length"] = len(parsed)

    return index


def _markdown_heading_index(lines: list[str]) -> list[dict[str, object]]:
    headings: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        level = len(stripped) - len(stripped.lstrip("#"))
        if level <= 0 or level > 6:
            continue
        text = stripped[level:].strip()
        if not text:
            continue
        headings.append({"line": line_number, "level": level, "text": text[:120]})
        if len(headings) >= 50:
            break
    return headings


def _code_block_ranges(lines: list[str]) -> list[dict[str, object]]:
    ranges: list[dict[str, object]] = []
    start_line = 0
    language = ""
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped.startswith("```"):
            continue
        if start_line == 0:
            start_line = line_number
            language = stripped[3:].strip()[:40]
            continue
        ranges.append({"start_line": start_line, "end_line": line_number, "language": language})
        if len(ranges) >= 50:
            break
        start_line = 0
        language = ""
    if start_line != 0 and len(ranges) < 50:
        ranges.append({"start_line": start_line, "end_line": len(lines), "language": language})
    return ranges


def _table_ranges(lines: list[str]) -> list[dict[str, int]]:
    return _consecutive_ranges(lines, lambda line: "|" in line and line.count("|") >= 2)


def _list_item_ranges(lines: list[str]) -> list[dict[str, int]]:
    return _consecutive_ranges(lines, _is_list_item_line)


def _is_list_item_line(line: str) -> bool:
    stripped = line.lstrip()
    if stripped.startswith(("- ", "* ")):
        return True
    marker = stripped.split(" ", 1)[0]
    return marker[:-1].isdigit() if marker.endswith((".", ")")) else False


def _consecutive_ranges(lines: list[str], predicate: Callable[[str], bool]) -> list[dict[str, int]]:
    ranges: list[dict[str, int]] = []
    start_line = 0
    for line_number, line in enumerate(lines, start=1):
        matches = predicate(line)
        if matches and start_line == 0:
            start_line = line_number
        elif not matches and start_line != 0:
            if line_number - start_line >= 2:
                ranges.append({"start_line": start_line, "end_line": line_number - 1})
                if len(ranges) >= 50:
                    return ranges
            start_line = 0
    if start_line != 0 and len(lines) - start_line >= 1 and len(ranges) < 50:
        ranges.append({"start_line": start_line, "end_line": len(lines)})
    return ranges


def _build_chunk_restore_args(archive_path: str, content: str) -> list[dict[str, str]]:
    """Build line-range restore args matching the lightweight content index."""
    lines = content.splitlines()
    line_count = len(lines)
    chunk_size = 200
    return [
        {"path": f"{archive_path}:{start + 1}-{min(start + chunk_size, line_count)}"}
        for start in range(0, min(line_count, chunk_size * 12), chunk_size)
    ]


def is_context_archive_path(path: str) -> bool:
    """Return True when a path points at a compacted context archive."""
    return extract_context_archive_session_id(path) is not None


def is_context_archive_path_for_session(path: str, session_id: str) -> bool:
    """Return True when the archive path belongs to the given session."""
    archive_session_id = extract_context_archive_session_id(path)
    return archive_session_id == session_id


def extract_context_archive_session_id(path: str) -> str | None:
    """Extract session id from .context/<session>/compacted/<file> paths."""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    for index, part in enumerate(parts):
        if part != ".context":
            continue
        session_index = index + 1
        compacted_index = index + 2
        if compacted_index >= len(parts):
            return None
        if parts[compacted_index] != "compacted":
            return None
        session_id = parts[session_index]
        return session_id or None
    return None
