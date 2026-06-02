"""Restore-map contract for content-addressed context archives.

[INPUT]
- json, re, time (POS: standard parsing and payload generation)
- pathlib::Path (POS: sidecar file lookup)
- runtime.execution_paths::get_context_archive_sidecar_path_candidates

[OUTPUT]
- build_restore_map_json: Build a schema-versioned restore-map payload.
- load_restore_map_ranges: Load validated restore ranges from archive sidecars.
- RestoreRangeHint / RestoreContentFeature: Bounded structural hints for UI-safe archive restore guidance.
- restore_map_payload_is_valid: Pure validator for archive store reuse checks.

[POS]
Runtime-owned restore-map protocol. Keeps archive writers and restore guidance
readers on the same schema, path normalization, and range validation rules.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.runtime.context.restore_map_structures import (
    RESTORE_MAP_RANGE_COUNT,
    RestoreContentFeature,
    RestoreRangeHint,
    build_content_index,
    build_recommended_restore_ranges,
    build_restore_content_features,
    build_restore_range_hints,
)
from myrm_agent_harness.runtime.execution_paths import get_context_archive_sidecar_path_candidates

RESTORE_MAP_SCHEMA_VERSION = 2
SUPPORTED_RESTORE_MAP_SCHEMA_VERSIONS = frozenset({1, RESTORE_MAP_SCHEMA_VERSION})
_RESTORE_RANGE_RE = re.compile(r"^(?P<path>.+):(?P<start>[1-9]\d*)-(?P<end>[1-9]\d*)$")


@dataclass(frozen=True, slots=True)
class RestoreMapLoadResult:
    """Validated restore-map sidecar lookup result."""

    ranges: tuple[str, ...]
    fallback_reason: str
    range_hints: tuple[RestoreRangeHint, ...] = ()
    content_features: tuple[RestoreContentFeature, ...] = ()

    @property
    def found(self) -> bool:
        return bool(self.ranges)


def build_restore_map_json(archive_path: str, restore_source: str | None) -> str | None:
    """Build a schema-v2 restore-map payload for the uncompressed source content."""
    if restore_source is None:
        return None

    lines = restore_source.splitlines() or [""]
    content_index = build_content_index(lines, restore_source)
    recommended_ranges, range_sources = build_recommended_restore_ranges(
        archive_path,
        lines,
        content_index,
    )
    payload: dict[str, object] = {
        "schema_version": RESTORE_MAP_SCHEMA_VERSION,
        "archive_path": archive_path,
        "line_count": len(lines),
        "content_index": content_index,
        "recommended_ranges": recommended_ranges,
        "range_sources": range_sources,
        "generated_at": time.time(),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def load_restore_map_ranges(archive_path: str, max_ranges: int) -> RestoreMapLoadResult:
    """Load validated restore ranges from the first usable sidecar candidate."""
    safe_max_ranges = max(max_ranges, 1)
    for sidecar_name in get_context_archive_sidecar_path_candidates(archive_path):
        sidecar_path = Path(sidecar_name)
        if not sidecar_path.is_file():
            continue

        try:
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return RestoreMapLoadResult(ranges=(), fallback_reason="restore_map_unreadable")

        ranges = extract_valid_restore_ranges(payload, archive_path, safe_max_ranges)
        if ranges:
            return RestoreMapLoadResult(
                ranges=ranges,
                fallback_reason="",
                range_hints=build_restore_range_hints(
                    payload,
                    archive_path,
                    ranges,
                    range_validator=restore_range_is_valid,
                    range_normalizer=_normalize_range_archive_path,
                ),
                content_features=build_restore_content_features(payload),
            )
        return RestoreMapLoadResult(ranges=(), fallback_reason="restore_map_invalid")

    return RestoreMapLoadResult(ranges=(), fallback_reason="restore_map_missing")


def restore_map_payload_is_valid(payload: object, archive_path: str) -> bool:
    """Return whether a restore-map sidecar is valid for this archive path."""
    if not isinstance(payload, dict) or payload.get("schema_version") != RESTORE_MAP_SCHEMA_VERSION:
        return False
    return bool(extract_valid_restore_ranges(payload, archive_path, RESTORE_MAP_RANGE_COUNT))


def extract_valid_restore_ranges(
    payload: object,
    archive_path: str,
    max_ranges: int,
) -> tuple[str, ...]:
    """Validate and normalize restore ranges from a restore-map payload."""
    if not isinstance(payload, dict):
        return ()
    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_RESTORE_MAP_SCHEMA_VERSIONS:
        return ()

    sidecar_archive_path = payload.get("archive_path")
    if not isinstance(sidecar_archive_path, str) or not sidecar_archive_path:
        return ()
    if not archive_path_matches(sidecar_archive_path, archive_path):
        return ()

    line_count = payload.get("line_count")
    if line_count is not None and (not isinstance(line_count, int) or line_count <= 0):
        return ()
    if schema_version == RESTORE_MAP_SCHEMA_VERSION and not isinstance(line_count, int):
        return ()
    if schema_version == RESTORE_MAP_SCHEMA_VERSION and not isinstance(payload.get("content_index"), dict):
        return ()

    raw_ranges = payload.get("recommended_ranges")
    if not isinstance(raw_ranges, list):
        return ()

    ranges: list[str] = []
    for raw_range in raw_ranges:
        if not isinstance(raw_range, str):
            continue
        if not restore_range_is_valid(raw_range, sidecar_archive_path, line_count):
            continue
        ranges.append(_normalize_range_archive_path(raw_range, sidecar_archive_path, archive_path))
        if len(ranges) >= max(max_ranges, 1):
            break
    return tuple(ranges)


def archive_path_matches(left: str, right: str) -> bool:
    """Return whether two archive path forms refer to the same archive."""
    left_forms = {left, left.lstrip("/")}
    right_forms = {right, right.lstrip("/")}
    if left.startswith("/persistent/"):
        left_forms.add(left[len("/persistent/") :])
    if right.startswith("/persistent/"):
        right_forms.add(right[len("/persistent/") :])
    return bool(left_forms & right_forms)


def restore_range_is_valid(raw_range: str, archive_path: str, line_count: int | None) -> bool:
    """Return whether a restore range points inside the archive."""
    match = _RESTORE_RANGE_RE.match(raw_range)
    if match is None:
        return False
    if not archive_path_matches(match.group("path"), archive_path):
        return False
    start = int(match.group("start"))
    end = int(match.group("end"))
    if start > end:
        return False
    return line_count is None or end <= line_count


def _normalize_range_archive_path(raw_range: str, source_archive_path: str, target_archive_path: str) -> str:
    match = _RESTORE_RANGE_RE.match(raw_range)
    if match is None:
        return raw_range
    if source_archive_path == target_archive_path and match.group("path") == target_archive_path:
        return raw_range
    return f"{target_archive_path}:{match.group('start')}-{match.group('end')}"


__all__ = [
    "RESTORE_MAP_SCHEMA_VERSION",
    "RestoreContentFeature",
    "RestoreMapLoadResult",
    "RestoreRangeHint",
    "archive_path_matches",
    "build_restore_map_json",
    "extract_valid_restore_ranges",
    "load_restore_map_ranges",
    "restore_map_payload_is_valid",
    "restore_range_is_valid",
]
