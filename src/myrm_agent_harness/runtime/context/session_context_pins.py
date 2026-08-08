"""Session-scoped pinned context files for cross-compaction retention.

[INPUT]
- runtime.execution_paths::PERSISTENT_ROOT (POS: persistent volume root)

[OUTPUT]
- read_pinned_files / write_pinned_files / add_pinned_file / remove_pinned_file

[POS]
Volume-backed pin registry consumed by the business layer when building compression_intent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.runtime.execution_paths import PERSISTENT_ROOT

_MAX_PINNED_FILES = 8
_PIN_FILENAME = "pinned_context_files.json"


@dataclass(frozen=True, slots=True)
class PinnedContextFiles:
    files: tuple[str, ...]
    updated_at: str


def _pin_path(session_id: str) -> Path:
    return Path(PERSISTENT_ROOT) / ".context" / session_id / _PIN_FILENAME


def read_pinned_files(session_id: str) -> list[str]:
    """Return pinned file paths for a session (empty when unset)."""
    if not session_id:
        return []
    path = _pin_path(session_id)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        return []
    return [item for item in raw_files if isinstance(item, str) and item][: _MAX_PINNED_FILES]


def write_pinned_files(session_id: str, files: list[str]) -> PinnedContextFiles:
    """Replace pinned files for a session."""
    if not session_id:
        raise ValueError("session_id is required")
    normalized = _normalize_files(files)
    path = _pin_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    updated_at = datetime.now(UTC).isoformat()
    path.write_text(
        json.dumps({"files": normalized, "updated_at": updated_at}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return PinnedContextFiles(files=tuple(normalized), updated_at=updated_at)


def add_pinned_file(session_id: str, file_path: str) -> PinnedContextFiles:
    """Append a pinned file with LRU eviction when over cap."""
    current = read_pinned_files(session_id)
    normalized_path = file_path.strip()
    if not normalized_path:
        return PinnedContextFiles(files=tuple(current), updated_at=datetime.now(UTC).isoformat())
    without_dup = [item for item in current if item != normalized_path]
    without_dup.append(normalized_path)
    if len(without_dup) > _MAX_PINNED_FILES:
        without_dup = without_dup[-_MAX_PINNED_FILES:]
    return write_pinned_files(session_id, without_dup)


def remove_pinned_file(session_id: str, file_path: str) -> PinnedContextFiles:
    """Remove one pinned file path."""
    normalized_path = file_path.strip()
    remaining = [item for item in read_pinned_files(session_id) if item != normalized_path]
    return write_pinned_files(session_id, remaining)


def _normalize_files(files: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in files:
        normalized = raw.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= _MAX_PINNED_FILES:
            break
    return deduped
