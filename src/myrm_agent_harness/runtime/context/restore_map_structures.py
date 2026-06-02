"""Structural index helpers for restore-map sidecars.

[INPUT]
- json (POS: standard JSON parsing for lightweight structure detection)
- re (POS: deterministic pattern matching)
- collections.abc::Callable (POS: callback typing for contract-owned validation)
- dataclasses::dataclass (POS: Python 数据类装饰器)

[OUTPUT]
- RestoreRangeHint / RestoreContentFeature: UI-safe restore structure DTOs.
- build_content_index: Build a bounded structure index for archived content.
- build_recommended_restore_ranges: Build source-tagged restore ranges.
- build_restore_range_hints / build_restore_content_features: Build UI-safe restore metadata.

[POS]
Restore-map structure helper layer. Keeps content indexing and UI-safe hint construction outside the archive contract reader/writer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

RESTORE_MAP_RANGE_COUNT = 3
RESTORE_MAP_CHUNK_LINES = 200

_RESTORE_KEYWORD_RE = re.compile(
    r"\b(error|exception|failed|failure|traceback|assert|timeout|denied|refused|warning)\b",
    re.IGNORECASE,
)
_RESTORE_RANGE_RE = re.compile(r"^(?P<path>.+):(?P<start>[1-9]\d*)-(?P<end>[1-9]\d*)$")


@dataclass(frozen=True, slots=True)
class RestoreRangeHint:
    """UI-safe structural hint for one restore range."""

    range_arg: str
    reason: str
    start_line: int
    end_line: int
    line: int

    def to_dict(self) -> dict[str, object]:
        return {
            "range_arg": self.range_arg,
            "reason": self.reason,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "line": self.line,
        }


@dataclass(frozen=True, slots=True)
class RestoreContentFeature:
    """Bounded structural feature summary from a restore-map content index."""

    feature_type: str
    count: int
    values: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_type": self.feature_type,
            "count": self.count,
            "values": list(self.values),
        }


def build_content_index(lines: list[str], content: str) -> dict[str, object]:
    line_count = len(lines)
    chunk_count = (line_count + RESTORE_MAP_CHUNK_LINES - 1) // RESTORE_MAP_CHUNK_LINES if line_count > 0 else 0
    chunk_ranges = [
        {"start_line": start + 1, "end_line": min(start + RESTORE_MAP_CHUNK_LINES, line_count)}
        for start in range(0, min(line_count, RESTORE_MAP_CHUNK_LINES * 12), RESTORE_MAP_CHUNK_LINES)
    ]
    index: dict[str, object] = {
        "line_count": line_count,
        "chunk_size_lines": RESTORE_MAP_CHUNK_LINES,
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
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return index
        if isinstance(parsed, dict):
            index["json_top_level_keys"] = [str(key) for key in list(parsed.keys())[:50]]
        elif isinstance(parsed, list):
            index["json_array_length"] = len(parsed)

    return index


def build_recommended_restore_ranges(
    archive_path: str,
    lines: list[str],
    content_index: dict[str, object],
) -> tuple[list[str], list[dict[str, object]]]:
    ranges: list[str] = []
    sources: list[dict[str, object]] = []

    for index, line in enumerate(lines, start=1):
        if not _RESTORE_KEYWORD_RE.search(line):
            continue
        _append_restore_range(
            ranges=ranges,
            sources=sources,
            archive_path=archive_path,
            line_number=index,
            line_count=len(lines),
            reason="error_keyword",
        )
        if len(ranges) >= RESTORE_MAP_RANGE_COUNT:
            return ranges, sources

    for field, reason in (
        ("markdown_headings", "section_heading"),
        ("code_block_ranges", "code_block"),
        ("table_ranges", "table_range"),
        ("list_item_ranges", "list_range"),
        ("chunk_ranges", "fallback_chunk"),
    ):
        if len(ranges) >= RESTORE_MAP_RANGE_COUNT:
            break
        for raw_range in _range_entries(content_index.get(field)):
            start = raw_range[0]
            end = raw_range[1]
            _append_exact_restore_range(
                ranges=ranges,
                sources=sources,
                archive_path=archive_path,
                start_line=start,
                end_line=end,
                reason=reason,
            )
            if len(ranges) >= RESTORE_MAP_RANGE_COUNT:
                return ranges, sources

    return ranges, sources


def build_restore_range_hints(
    payload: object,
    archive_path: str,
    ranges: tuple[str, ...],
    *,
    range_validator: Callable[[str, str, int | None], bool],
    range_normalizer: Callable[[str, str, str], str],
) -> tuple[RestoreRangeHint, ...]:
    if not isinstance(payload, dict):
        return ()

    raw_archive_path = payload.get("archive_path")
    sidecar_archive_path = raw_archive_path if isinstance(raw_archive_path, str) else archive_path
    sources_by_range = _range_sources_by_normalized_range(
        payload,
        source_archive_path=sidecar_archive_path,
        target_archive_path=archive_path,
        range_validator=range_validator,
        range_normalizer=range_normalizer,
    )
    hints: list[RestoreRangeHint] = []
    for restore_range in ranges:
        match = _RESTORE_RANGE_RE.match(restore_range)
        if match is None:
            continue
        start_line = int(match.group("start"))
        end_line = int(match.group("end"))
        source = sources_by_range.get(restore_range, {})
        hints.append(
            RestoreRangeHint(
                range_arg=restore_range,
                reason=_source_reason(source),
                start_line=start_line,
                end_line=end_line,
                line=_source_line(source, start_line),
            )
        )
    return tuple(hints)


def build_restore_content_features(payload: object) -> tuple[RestoreContentFeature, ...]:
    if not isinstance(payload, dict):
        return ()
    content_index = payload.get("content_index")
    if not isinstance(content_index, dict):
        return ()

    features: list[RestoreContentFeature] = []
    json_keys = _str_items(content_index.get("json_top_level_keys"), limit=8)
    if json_keys:
        features.append(
            RestoreContentFeature(
                feature_type="json_keys",
                count=_list_count(content_index.get("json_top_level_keys")),
                values=tuple(json_keys),
            )
        )

    json_array_length = content_index.get("json_array_length")
    if isinstance(json_array_length, int) and json_array_length >= 0:
        features.append(RestoreContentFeature(feature_type="json_array", count=json_array_length))

    for field, feature_type in (
        ("markdown_headings", "markdown_headings"),
        ("code_block_ranges", "code_blocks"),
        ("table_ranges", "tables"),
        ("list_item_ranges", "lists"),
        ("chunk_ranges", "chunks"),
    ):
        count = _list_count(content_index.get(field))
        if count > 0:
            features.append(RestoreContentFeature(feature_type=feature_type, count=count))

    return tuple(features)


def _range_sources_by_normalized_range(
    payload: dict[str, object],
    *,
    source_archive_path: str,
    target_archive_path: str,
    range_validator: Callable[[str, str, int | None], bool],
    range_normalizer: Callable[[str, str, str], str],
) -> dict[str, dict[str, object]]:
    raw_sources = payload.get("range_sources")
    if not isinstance(raw_sources, list):
        return {}

    sources: dict[str, dict[str, object]] = {}
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            continue
        raw_range = raw_source.get("range")
        if not isinstance(raw_range, str):
            continue
        if not range_validator(raw_range, source_archive_path, None):
            continue
        normalized_range = range_normalizer(raw_range, source_archive_path, target_archive_path)
        sources[normalized_range] = raw_source
    return sources


def _source_reason(source: dict[str, object]) -> str:
    reason = source.get("reason")
    return reason if isinstance(reason, str) and reason else "restore_map_range"


def _source_line(source: dict[str, object], fallback_line: int) -> int:
    line = source.get("line")
    return line if isinstance(line, int) and line > 0 else fallback_line


def _str_items(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for raw_item in value:
        if not isinstance(raw_item, str) or not raw_item:
            continue
        items.append(raw_item[:80])
        if len(items) >= limit:
            break
    return items


def _list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _range_entries(value: object) -> list[tuple[int, int]]:
    if not isinstance(value, list):
        return []
    entries: list[tuple[int, int]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            continue
        start = raw_item.get("start_line") or raw_item.get("line")
        end = raw_item.get("end_line") or start
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start <= 0 or end < start:
            continue
        entries.append((start, end))
    return entries


def _append_restore_range(
    *,
    ranges: list[str],
    sources: list[dict[str, object]],
    archive_path: str,
    line_number: int,
    line_count: int,
    reason: str,
) -> None:
    start = max(1, line_number - 40)
    end = min(line_count, start + RESTORE_MAP_CHUNK_LINES - 1)
    _append_exact_restore_range(
        ranges=ranges,
        sources=sources,
        archive_path=archive_path,
        start_line=start,
        end_line=end,
        reason=reason,
        line=line_number,
    )


def _append_exact_restore_range(
    *,
    ranges: list[str],
    sources: list[dict[str, object]],
    archive_path: str,
    start_line: int,
    end_line: int,
    reason: str,
    line: int | None = None,
) -> None:
    range_arg = f"{archive_path}:{start_line}-{end_line}"
    if range_arg in ranges:
        return
    ranges.append(range_arg)
    source: dict[str, object] = {"range": range_arg, "reason": reason, "line": line or start_line}
    sources.append(source)


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


__all__ = [
    "RESTORE_MAP_CHUNK_LINES",
    "RESTORE_MAP_RANGE_COUNT",
    "RestoreContentFeature",
    "RestoreRangeHint",
    "build_content_index",
    "build_recommended_restore_ranges",
    "build_restore_content_features",
    "build_restore_range_hints",
]
