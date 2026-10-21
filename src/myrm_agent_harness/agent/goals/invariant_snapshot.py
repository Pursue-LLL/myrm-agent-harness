"""Post-hoc tamper detection for Goal-protected files.

Captures SHA-256 hashes of files matching ``Goal.protected_paths`` at Goal
activation time, and verifies integrity before the Goal is marked complete.
This is the safety-net layer that catches modifications made through channels
that bypass the file_write_tool validator chain (e.g. ``bash_code_execute_tool``).

Pattern resolution goes through the shared matcher in
``core.security.path.pattern``, the same one the pre-write
``InvariantValidator`` uses, so the two layers can never disagree about which
files are protected.

A pattern that matches nothing leaves no baseline to verify, which is a
configuration error rather than an all-clear: ``capture_protected_snapshot``
reports it at Goal start and ``verify_protected_integrity`` reports it again
instead of logging an intact result for an empty baseline.

[INPUT]
- .types::Goal (POS: Goal data model with protected_paths)
- core.security.path.pattern::iter_matching_files (POS: shared pattern matcher + bounded walk)

[OUTPUT]
- capture_protected_snapshot: Hash all files matching protected_paths at Goal start.
- verify_protected_integrity: Re-hash and compare at Goal completion time.
- ProtectedFileViolation: Dataclass describing a detected tamper.

[POS]
Provides post-hoc tamper detection for Goal-protected files.
Complements InvariantValidator (pre-write block) by catching bash_code_execute_tool bypasses.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field

from myrm_agent_harness.core.security.path.pattern import (
    first_matching_pattern,
    iter_matching_files,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProtectedFileViolation:
    """Describes a detected modification to a protected file."""

    path: str
    pattern: str
    kind: str  # "modified" | "deleted" | "created"


@dataclass
class _ProtectedSnapshot:
    """Baseline for one Goal: file hashes plus the rules that produced them."""

    hashes: dict[str, str] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)
    workspace_root: str = ""


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


def _resolve_patterns(patterns: list[str], workspace_root: str) -> tuple[dict[str, str], list[str]]:
    """Hash every file under workspace_root that any pattern protects.

    Returns (hashes_by_absolute_path, patterns_that_matched_nothing).
    """
    snapshot: dict[str, str] = {}
    matched: set[str] = set()

    for entry in iter_matching_files(workspace_root, patterns):
        matched.add(entry.pattern)
        abs_path = os.path.abspath(entry.path)
        if abs_path not in snapshot:
            snapshot[abs_path] = _file_hash(abs_path)

    return snapshot, [pattern for pattern in patterns if pattern not in matched]


# Module-level storage keyed by goal_id (not ContextVar, same reason as CompletionGuard).
_snapshots: dict[str, _ProtectedSnapshot] = {}


def capture_protected_snapshot(goal_id: str, patterns: list[str], workspace_root: str) -> int:
    """Capture baseline hashes for all files matching the Goal's protected_paths.

    Call this when a Goal is activated.
    Returns the number of files captured.
    """
    if not patterns:
        return 0

    hashes, unmatched = _resolve_patterns(patterns, workspace_root)
    _snapshots[goal_id] = _ProtectedSnapshot(
        hashes=hashes,
        patterns=list(patterns),
        workspace_root=workspace_root,
    )

    logger.info(
        "[InvariantSnapshot] Captured %d protected files for goal %s (%d patterns)",
        len(hashes),
        goal_id,
        len(patterns),
    )
    if unmatched:
        # A pattern that protects nothing would otherwise let a tampered file
        # pass verification and report an intact result.
        logger.warning(
            "[InvariantSnapshot] %d pattern(s) matched no file for goal %s and protect nothing: %s",
            len(unmatched),
            goal_id,
            ", ".join(unmatched),
        )
    return len(hashes)


def verify_protected_integrity(goal_id: str) -> list[ProtectedFileViolation]:
    """Verify that no protected files have been tampered with since capture.

    Call this before marking a Goal as complete.
    Returns a list of violations (empty = all intact).
    Non-destructive: snapshot remains until explicitly cleared via clear_snapshot().
    """
    entry = _snapshots.get(goal_id)
    if entry is None:
        return []

    original_snapshot = entry.hashes
    patterns = entry.patterns
    current_snapshot, _ = _resolve_patterns(patterns, entry.workspace_root)

    violations: list[ProtectedFileViolation] = []

    for path, original_hash in original_snapshot.items():
        current_hash = current_snapshot.get(path)
        if current_hash is None:
            violations.append(
                ProtectedFileViolation(
                    path=path,
                    pattern=_find_matching_pattern(path, patterns),
                    kind="deleted",
                )
            )
        elif current_hash != original_hash:
            violations.append(
                ProtectedFileViolation(
                    path=path,
                    pattern=_find_matching_pattern(path, patterns),
                    kind="modified",
                )
            )

    for path in current_snapshot:
        if path not in original_snapshot:
            violations.append(
                ProtectedFileViolation(
                    path=path,
                    pattern=_find_matching_pattern(path, patterns),
                    kind="created",
                )
            )

    if violations:
        logger.warning(
            "[InvariantSnapshot] %d violation(s) detected for goal %s: %s",
            len(violations),
            goal_id,
            ", ".join(f"{v.path} ({v.kind})" for v in violations),
        )
    elif original_snapshot:
        logger.info("[InvariantSnapshot] All protected files intact for goal %s", goal_id)
    else:
        # No baseline means nothing was ever covered, which is a configuration
        # error rather than proof of integrity.
        logger.warning(
            "[InvariantSnapshot] Goal %s has no protected files to verify; its protection rules matched nothing",
            goal_id,
        )

    return violations


def register_protected_artifact(goal_id: str, file_path: str, workspace_root: str | None = None) -> bool:
    """Dynamically register a newly created artifact (e.g. test file) into protected snapshot.

    Computes SHA-256 and locks the file so subsequent tampering or weakening
    during continuation self-healing turns will be caught and blocked.
    Returns True if successfully registered, False if file cannot be read.
    """
    entry = _snapshots.get(goal_id)
    if not os.path.isabs(file_path):
        root = workspace_root or (entry.workspace_root if entry else "") or os.getcwd()
        abs_path = os.path.abspath(os.path.join(root, file_path))
    else:
        abs_path = os.path.abspath(file_path)

    file_hash = _file_hash(abs_path)
    if not file_hash:
        logger.warning(
            "[InvariantSnapshot] Failed to hash artifact for goal %s: %s",
            goal_id,
            abs_path,
        )
        return False

    if entry is None:
        _snapshots[goal_id] = _ProtectedSnapshot(
            hashes={abs_path: file_hash},
            patterns=[file_path],
            workspace_root=workspace_root or os.path.dirname(abs_path),
        )
    else:
        entry.hashes[abs_path] = file_hash
        if file_path not in entry.patterns and abs_path not in entry.patterns:
            entry.patterns.append(file_path)

    logger.info(
        "[InvariantSnapshot] Dynamically protected artifact for goal %s: %s (sha256=%s)",
        goal_id,
        abs_path,
        file_hash[:8],
    )
    return True


def clear_snapshot(goal_id: str) -> None:
    """Clear the snapshot for a goal (e.g. on cancellation)."""
    _snapshots.pop(goal_id, None)


def _find_matching_pattern(path: str, patterns: list[str]) -> str:
    """Find which pattern a path matches (best-effort for error reporting)."""
    return first_matching_pattern(path, patterns) or (patterns[0] if patterns else "")
