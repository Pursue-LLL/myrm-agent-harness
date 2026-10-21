"""Typed archive restore action materialization.

[INPUT]
- agent.context_management.infra.archive_reference (POS: session-scoped archive path guards)
- agent.context_management.tracking.archive_restore_runtime (POS: restore budget/outcome accounting)
- runtime.context.restore_map_contract (POS: restore-map range validation)

[OUTPUT]
- ArchiveRestoreActionError: stable restore action validation failure.
- MaterializedArchiveRestore: validated range content ready for prompt injection.
- materialize_archive_restore_action: validate and read a targeted archive range.

[POS]
Runtime contract for GUI/server typed archive restore actions. The action restores only an explicit
line range from the current session archive and records the same budget metrics as file-tool reads.
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape, quoteattr

from myrm_agent_harness.agent.context_management.infra.archive_reference import (
    is_context_archive_path_for_session,
)
from myrm_agent_harness.agent.context_management.tracking.archive_restore_runtime import (
    evaluate_archive_refetch_for_path,
    record_archive_restore_result_for_path,
)
from myrm_agent_harness.runtime.context.restore_map_contract import restore_range_is_valid
from myrm_agent_harness.utils.text_utils import get_token_count

_RESTORE_ARG_RE = re.compile(r"^(?P<path>.+):(?P<start>[1-9]\d*)-(?P<end>[1-9]\d*)$")
_MAX_RANGE_LINES = 600
_LINE_INDEX_SCHEMA_VERSION = 1
_LINE_INDEX_STRIDE = 256
_LINE_INDEX_MIN_START_LINE = 2048


class ArchiveRestoreActionError(ValueError):
    """Stable validation failure for typed archive restore actions."""


@dataclass(frozen=True, slots=True)
class ArchiveRestoreResult:
    """UI-safe restore result metadata without restored content."""

    archive_path: str
    restore_arg: str
    start_line: int
    end_line: int
    restored_line_count: int
    estimated_tokens: int
    restored_bytes: int
    outcome: Literal["restored"] = "restored"

    def to_dict(self) -> dict[str, object]:
        return {
            "type": "archive_restore_result",
            "outcome": self.outcome,
            "archive_path": self.archive_path,
            "restore_arg": self.restore_arg,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "restored_line_count": self.restored_line_count,
            "estimated_tokens": self.estimated_tokens,
            "restored_bytes": self.restored_bytes,
        }


@dataclass(frozen=True, slots=True)
class MaterializedArchiveRestore:
    """Validated archive range content for injection into the next agent input."""

    archive_path: str
    restore_arg: str
    start_line: int
    end_line: int
    content: str
    estimated_tokens: int

    def render_xml(self) -> str:
        return (
            f"<archive_restore archive_path={quoteattr(self.archive_path)} "
            f"range={quoteattr(f'{self.start_line}-{self.end_line}')} "
            f"restore_arg={quoteattr(self.restore_arg)} "
            f"estimated_tokens={quoteattr(str(self.estimated_tokens))}>\n"
            f"{escape(self.content)}\n"
            f"</archive_restore>"
        )

    def to_result(self) -> ArchiveRestoreResult:
        return ArchiveRestoreResult(
            archive_path=self.archive_path,
            restore_arg=self.restore_arg,
            start_line=self.start_line,
            end_line=self.end_line,
            restored_line_count=self.end_line - self.start_line + 1,
            estimated_tokens=self.estimated_tokens,
            restored_bytes=len(self.content.encode("utf-8")),
        )


@dataclass(frozen=True, slots=True)
class _ArchiveLineOffsetIndex:
    """Sparse byte-offset index for late archive range reads."""

    file_size: int
    mtime_ns: int
    line_count: int
    stride: int
    offsets: tuple[tuple[int, int], ...]


async def materialize_archive_restore_action(
    *,
    workspace_dir: str,
    chat_id: str,
    restore_arg: str,
    record_allowed: bool = True,
) -> MaterializedArchiveRestore:
    """Validate and read a typed archive restore action."""

    archive_path, start_line, end_line = _parse_restore_arg(restore_arg)
    if end_line - start_line + 1 > _MAX_RANGE_LINES:
        raise ArchiveRestoreActionError(f"Archive restore range exceeds {_MAX_RANGE_LINES} lines.")
    if not is_context_archive_path_for_session(archive_path, chat_id):
        raise ArchiveRestoreActionError("Archive restore action does not belong to the current session.")

    absolute_path = _resolve_workspace_archive_path(workspace_dir, archive_path)
    content, line_count = await _read_line_range(absolute_path, start_line, end_line)
    if not restore_range_is_valid(restore_arg, archive_path, line_count):
        raise ArchiveRestoreActionError("Archive restore range is outside the archive.")

    estimated_tokens = get_token_count(content)
    decision = evaluate_archive_refetch_for_path(
        archive_path,
        estimated_tokens=estimated_tokens,
        current_chat_id=chat_id,
        is_range_read=True,
        record_allowed=record_allowed,
    )
    if decision.is_archive_path and not decision.allowed:
        raise ArchiveRestoreActionError(decision.message or "Archive restore blocked.")

    if record_allowed:
        record_archive_restore_result_for_path(
            archive_path,
            restore_arg=restore_arg,
            start_line=start_line,
            end_line=end_line,
            restored_line_count=end_line - start_line + 1,
            estimated_tokens=estimated_tokens,
            restored_bytes=len(content.encode("utf-8")),
            current_chat_id=chat_id,
        )

    return MaterializedArchiveRestore(
        archive_path=archive_path,
        restore_arg=restore_arg,
        start_line=start_line,
        end_line=end_line,
        content=content,
        estimated_tokens=estimated_tokens,
    )


def _parse_restore_arg(restore_arg: str) -> tuple[str, int, int]:
    match = _RESTORE_ARG_RE.match(restore_arg.strip())
    if match is None:
        raise ArchiveRestoreActionError("Archive restore action must use '<archive_path>:<start>-<end>'.")
    start_line = int(match.group("start"))
    end_line = int(match.group("end"))
    if start_line > end_line:
        raise ArchiveRestoreActionError("Archive restore range start exceeds end.")
    return match.group("path"), start_line, end_line


def _resolve_workspace_archive_path(workspace_dir: str, archive_path: str) -> Path:
    workspace_root = Path(workspace_dir).expanduser().resolve()
    relative_path = archive_path.lstrip("/")
    absolute_path = (workspace_root / relative_path).resolve()
    try:
        absolute_path.relative_to(workspace_root)
    except ValueError as exc:
        raise ArchiveRestoreActionError("Archive restore path is outside the current workspace.") from exc
    if not absolute_path.is_file():
        raise ArchiveRestoreActionError("Archive restore file does not exist.")
    return absolute_path


async def _read_line_range(path: Path, start_line: int, end_line: int) -> tuple[str, int]:
    return await asyncio.to_thread(_read_line_range_sync, path, start_line, end_line)


def _read_line_range_sync(path: Path, start_line: int, end_line: int) -> tuple[str, int]:
    if _should_use_line_offset_index(path, start_line):
        indexed_result = _read_line_range_with_index(path, start_line, end_line)
        if indexed_result is not None:
            return indexed_result
    return _read_line_range_streaming_sync(path, start_line, end_line)


def _read_line_range_streaming_sync(path: Path, start_line: int, end_line: int) -> tuple[str, int]:
    selected_lines: list[str] = []
    observed_line_count = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for observed_line_count, raw_line in enumerate(handle, start=1):
                if start_line <= observed_line_count <= end_line:
                    selected_lines.append(raw_line.rstrip("\n").rstrip("\r"))
                if observed_line_count >= end_line:
                    break
    except OSError as exc:
        raise ArchiveRestoreActionError("Archive restore file could not be read.") from exc
    if observed_line_count < end_line:
        raise ArchiveRestoreActionError("Archive restore range is outside the archive.")
    return "\n".join(selected_lines), observed_line_count


def _should_use_line_offset_index(path: Path, start_line: int) -> bool:
    if start_line >= _LINE_INDEX_MIN_START_LINE:
        return True
    return _line_index_path(path).is_file()


def _read_line_range_with_index(path: Path, start_line: int, end_line: int) -> tuple[str, int] | None:
    try:
        line_index = _load_or_build_line_offset_index(path)
    except ArchiveRestoreActionError:
        raise
    except OSError:
        return None
    if end_line > line_index.line_count:
        raise ArchiveRestoreActionError("Archive restore range is outside the archive.")
    start_at_line, byte_offset = _nearest_index_offset(line_index, start_line)
    selected_lines: list[str] = []
    current_line = start_at_line
    try:
        with path.open("rb") as handle:
            handle.seek(byte_offset)
            while current_line <= end_line:
                raw_line = handle.readline()
                if raw_line == b"":
                    break
                if current_line >= start_line:
                    selected_lines.append(raw_line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r"))
                current_line += 1
    except OSError as exc:
        raise ArchiveRestoreActionError("Archive restore file could not be read.") from exc
    if current_line <= end_line:
        raise ArchiveRestoreActionError("Archive restore range is outside the archive.")
    return "\n".join(selected_lines), line_index.line_count


def _load_or_build_line_offset_index(path: Path) -> _ArchiveLineOffsetIndex:
    stat_result = path.stat()
    index_path = _line_index_path(path)
    existing_index = _load_line_offset_index(
        index_path, file_size=stat_result.st_size, mtime_ns=stat_result.st_mtime_ns
    )
    if existing_index is not None:
        return existing_index
    line_index = _build_line_offset_index(path, file_size=stat_result.st_size, mtime_ns=stat_result.st_mtime_ns)
    _write_line_offset_index(index_path, line_index)
    return line_index


def _line_index_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.line_index.json")


def _load_line_offset_index(index_path: Path, *, file_size: int, mtime_ns: int) -> _ArchiveLineOffsetIndex | None:
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _LINE_INDEX_SCHEMA_VERSION:
        return None
    if payload.get("file_size") != file_size or payload.get("mtime_ns") != mtime_ns:
        return None
    line_count = payload.get("line_count")
    stride = payload.get("stride")
    if not _is_non_negative_int(line_count) or not _is_positive_int(stride):
        return None
    offsets = _parse_line_offsets(payload.get("offsets"), line_count=line_count)
    if offsets is None:
        return None
    return _ArchiveLineOffsetIndex(
        file_size=file_size,
        mtime_ns=mtime_ns,
        line_count=line_count,
        stride=stride,
        offsets=offsets,
    )


def _parse_line_offsets(raw_offsets: object, *, line_count: int) -> tuple[tuple[int, int], ...] | None:
    if not isinstance(raw_offsets, list):
        return None
    offsets: list[tuple[int, int]] = []
    previous_line = 0
    previous_offset = -1
    for raw_item in raw_offsets:
        if not isinstance(raw_item, list) or len(raw_item) != 2:
            return None
        raw_line, raw_offset = raw_item
        if not _is_positive_int(raw_line) or not _is_non_negative_int(raw_offset):
            return None
        if raw_line <= previous_line or raw_offset < previous_offset or raw_line > max(line_count, 1):
            return None
        offsets.append((raw_line, raw_offset))
        previous_line = raw_line
        previous_offset = raw_offset
    if line_count > 0 and (not offsets or offsets[0] != (1, 0)):
        return None
    return tuple(offsets)


def _build_line_offset_index(path: Path, *, file_size: int, mtime_ns: int) -> _ArchiveLineOffsetIndex:
    offsets: list[tuple[int, int]] = []
    line_count = 0
    try:
        with path.open("rb") as handle:
            while True:
                byte_offset = handle.tell()
                raw_line = handle.readline()
                if raw_line == b"":
                    break
                line_count += 1
                if (line_count - 1) % _LINE_INDEX_STRIDE == 0:
                    offsets.append((line_count, byte_offset))
    except OSError as exc:
        raise ArchiveRestoreActionError("Archive restore file could not be read.") from exc
    return _ArchiveLineOffsetIndex(
        file_size=file_size,
        mtime_ns=mtime_ns,
        line_count=line_count,
        stride=_LINE_INDEX_STRIDE,
        offsets=tuple(offsets),
    )


def _write_line_offset_index(index_path: Path, line_index: _ArchiveLineOffsetIndex) -> None:
    payload: dict[str, object] = {
        "schema_version": _LINE_INDEX_SCHEMA_VERSION,
        "file_size": line_index.file_size,
        "mtime_ns": line_index.mtime_ns,
        "line_count": line_index.line_count,
        "stride": line_index.stride,
        "offsets": [[line, offset] for line, offset in line_index.offsets],
    }
    temporary_path = index_path.with_name(f"{index_path.name}.tmp")
    try:
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary_path.replace(index_path)
    except OSError:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)
        return


def _nearest_index_offset(line_index: _ArchiveLineOffsetIndex, start_line: int) -> tuple[int, int]:
    selected = (1, 0)
    for indexed_line, byte_offset in line_index.offsets:
        if indexed_line > start_line:
            break
        selected = (indexed_line, byte_offset)
    return selected


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = [
    "ArchiveRestoreActionError",
    "MaterializedArchiveRestore",
    "materialize_archive_restore_action",
]
