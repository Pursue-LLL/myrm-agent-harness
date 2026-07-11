"""Post-hoc tamper detection for Goal-protected files.

Captures SHA-256 hashes of files matching ``Goal.protected_paths`` at Goal
activation time, and verifies integrity before the Goal is marked complete.
This is the safety-net layer that catches modifications made through channels
that bypass the file_write_tool validator chain (e.g. ``bash_code_execute_tool``).

[INPUT]
- .types::Goal (POS: Goal data model with protected_paths)

[OUTPUT]
- capture_protected_snapshot: Hash all files matching protected_paths at Goal start.
- verify_protected_integrity: Re-hash and compare at Goal completion time.
- ProtectedFileViolation: Dataclass describing a detected tamper.

[POS]
Provides post-hoc tamper detection for Goal-protected files.
Complements InvariantValidator (pre-write block) by catching bash_code_execute_tool bypasses.
"""

from __future__ import annotations

import glob
import hashlib
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProtectedFileViolation:
    """Describes a detected modification to a protected file."""

    path: str
    pattern: str
    kind: str  # "modified" | "deleted" | "created"


def _file_hash(path: str) -> str:
    """Compute SHA-256 hex digest of a file. Returns empty string for unreadable files."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _resolve_patterns(patterns: list[str], workspace_root: str) -> dict[str, str]:
    """Expand glob patterns relative to workspace_root and hash all matching files.

    Returns a dict of {absolute_path: sha256_hex}.
    """
    snapshot: dict[str, str] = {}
    for pattern in patterns:
        full_pattern = os.path.join(workspace_root, pattern) if not os.path.isabs(pattern) else pattern
        for path in glob.glob(full_pattern, recursive=True):
            if os.path.isfile(path):
                abs_path = os.path.abspath(path)
                if abs_path not in snapshot:
                    snapshot[abs_path] = _file_hash(abs_path)
    return snapshot


# Module-level storage keyed by goal_id (not ContextVar, same reason as CompletionGuard).
_snapshots: dict[str, tuple[dict[str, str], list[str], str]] = {}


def capture_protected_snapshot(goal_id: str, patterns: list[str], workspace_root: str) -> int:
    """Capture baseline hashes for all files matching the Goal's protected_paths.

    Call this when a Goal is activated.
    Returns the number of files captured.
    """
    if not patterns:
        return 0

    snapshot = _resolve_patterns(patterns, workspace_root)
    _snapshots[goal_id] = (snapshot, patterns, workspace_root)

    logger.info(
        "[InvariantSnapshot] Captured %d protected files for goal %s (%d patterns)",
        len(snapshot),
        goal_id,
        len(patterns),
    )
    return len(snapshot)


def verify_protected_integrity(goal_id: str) -> list[ProtectedFileViolation]:
    """Verify that no protected files have been tampered with since capture.

    Call this before marking a Goal as complete.
    Returns a list of violations (empty = all intact).
    Non-destructive: snapshot remains until explicitly cleared via clear_snapshot().
    """
    entry = _snapshots.get(goal_id)
    if entry is None:
        return []

    original_snapshot, patterns, workspace_root = entry
    current_snapshot = _resolve_patterns(patterns, workspace_root)

    violations: list[ProtectedFileViolation] = []

    for path, original_hash in original_snapshot.items():
        current_hash = current_snapshot.get(path)
        if current_hash is None:
            violations.append(ProtectedFileViolation(path=path, pattern=_find_matching_pattern(path, patterns), kind="deleted"))
        elif current_hash != original_hash:
            violations.append(ProtectedFileViolation(path=path, pattern=_find_matching_pattern(path, patterns), kind="modified"))

    for path in current_snapshot:
        if path not in original_snapshot:
            violations.append(ProtectedFileViolation(path=path, pattern=_find_matching_pattern(path, patterns), kind="created"))

    if violations:
        logger.warning(
            "[InvariantSnapshot] %d violation(s) detected for goal %s: %s",
            len(violations),
            goal_id,
            ", ".join(f"{v.path} ({v.kind})" for v in violations),
        )
    else:
        logger.info("[InvariantSnapshot] All protected files intact for goal %s", goal_id)

    return violations


def clear_snapshot(goal_id: str) -> None:
    """Clear the snapshot for a goal (e.g. on cancellation)."""
    _snapshots.pop(goal_id, None)


def _find_matching_pattern(path: str, patterns: list[str]) -> str:
    """Find which pattern a path matches (best-effort for error reporting)."""
    from fnmatch import fnmatch

    for pattern in patterns:
        if fnmatch(path, pattern) or fnmatch(os.path.basename(path), pattern):
            return pattern
    return patterns[0] if patterns else ""
