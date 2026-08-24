"""Sandbox mount security gate — fail-closed verification for sandbox filesystem mounts.

Single source of truth for sandbox filesystem mount validation across local OS process
sandboxes (bwrap, seatbelt, appcontainer) and multi-session workspace directory grants.

[INPUT]
- core.security.path_security::DANGEROUS_PATHS, is_dangerous_path, is_blocked_device_path, is_within_boundary

[OUTPUT]
- MountMode (Enum: RO, RW)
- MountViolationType (Enum: NULL_BYTE, PATH_TRAVERSAL, DANGEROUS_PATH, BLOCKED_DEVICE, SYMLINK_ESCAPE, PERMISSION_VIOLATION, UNAUTHORIZED_BOUNDARY)
- MountSpec (immutable dataclass)
- MountValidationResult (immutable dataclass)
- validate_mount_spec(spec, ...) -> MountValidationResult
- validate_and_sanitize_mounts(mounts, ...) -> tuple[MountSpec, ...]

[POS]
Layer 2.5 / Toolkit Sandbox Security Domain component ensuring all directory mounts
in OS sandboxes and container volume mappings strictly conform to boundary and safety rules.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.core.security.path_security import (
    is_blocked_device_path,
    is_dangerous_path,
)

logger = logging.getLogger(__name__)


class MountMode(StrEnum):
    """Mount access mode."""

    RO = "ro"
    RW = "rw"


class MountViolationType(StrEnum):
    """Specific classification of a mount security violation."""

    NULL_BYTE = "null_byte"
    EMPTY_PATH = "empty_path"
    PATH_TRAVERSAL = "path_traversal"
    DANGEROUS_PATH = "dangerous_path"
    BLOCKED_DEVICE = "blocked_device"
    SYMLINK_ESCAPE = "symlink_escape"
    PERMISSION_VIOLATION = "permission_violation"
    UNAUTHORIZED_BOUNDARY = "unauthorized_boundary"


@dataclass(frozen=True, slots=True)
class MountSpec:
    """Immutable specification for a sandbox filesystem mount.

    Attributes:
        source_path: Host file or directory path.
        target_path: In-sandbox destination path (defaults to source_path if empty).
        mode: Mount mode (RO or RW).
        label: Optional description or tag.
    """

    source_path: str
    target_path: str = ""
    mode: MountMode = MountMode.RW
    label: str = ""

    @property
    def is_writable(self) -> bool:
        return self.mode == MountMode.RW


@dataclass(frozen=True, slots=True)
class MountValidationResult:
    """Immutable verdict produced by SandboxMountSecurityGate."""

    is_valid: bool
    sanitized_spec: MountSpec | None = None
    violation_type: MountViolationType | None = None
    error_message: str = ""


def _normalize_case_for_os(path_str: str) -> str:
    """Normalize path string casing on case-insensitive filesystems (macOS / Windows)."""
    if sys.platform in ("darwin", "win32"):
        return os.path.normcase(path_str)
    return path_str


def _resolve_physical_path(raw_path: str) -> str:
    """Resolve physical realpath, handling existing vs pending non-existent subpaths securely."""
    expanded = os.path.expanduser(raw_path.strip())
    if os.path.exists(expanded):
        return os.path.realpath(expanded)

    # For pending targets that do not exist yet, resolve existing parent chain
    parts = []
    curr = expanded
    while curr and not os.path.exists(curr):
        parent, tail = os.path.split(curr)
        if not tail or parent == curr:
            break
        parts.append(tail)
        curr = parent

    resolved_parent = os.path.realpath(curr) if os.path.exists(curr) else curr
    for tail in reversed(parts):
        resolved_parent = os.path.join(resolved_parent, tail)
    return os.path.normpath(resolved_parent)


def _is_path_enclosed_in_boundary(target_path: str, boundary_path: str) -> bool:
    """Check if target_path is enclosed within boundary_path using physical realpaths."""
    try:
        t_real = _resolve_physical_path(target_path)
        b_real = _resolve_physical_path(boundary_path)

        t_cmp = _normalize_case_for_os(t_real)
        b_cmp = _normalize_case_for_os(b_real)

        # Enclosure check
        if t_cmp == b_cmp or t_cmp.startswith(b_cmp + os.sep) or (b_cmp.endswith(os.sep) and t_cmp.startswith(b_cmp)):
            return True
        return False
    except Exception:
        return False


def validate_mount_spec(
    spec: MountSpec,
    *,
    allowed_boundaries: tuple[str, ...] = (),
    require_write: bool | None = None,
    allow_dangerous_override: bool = False,
) -> MountValidationResult:
    """Validate a single mount spec against all sandbox mount security rules.

    Verification pipeline:
    1. Null byte & empty string check.
    2. Blocked device check (CON, NUL, COM*, \\\\.\\*, /dev/*).
    3. Traversal (..) check.
    4. Dangerous host system paths check (/etc, /proc, ~/.ssh, etc.).
    5. Symlink escape & boundary enclosure check.
    6. Read-Only vs Read-Write least privilege enforcement.
    """
    raw_src = spec.source_path
    if "\0" in raw_src:
        return MountValidationResult(
            is_valid=False,
            violation_type=MountViolationType.NULL_BYTE,
            error_message=f"Null byte injection detected in mount source: {raw_src!r}",
        )

    trimmed = raw_src.strip()
    if not trimmed:
        return MountValidationResult(
            is_valid=False,
            violation_type=MountViolationType.EMPTY_PATH,
            error_message="Mount source path cannot be empty",
        )

    # 2. Blocked device check
    if is_blocked_device_path(trimmed):
        return MountValidationResult(
            is_valid=False,
            violation_type=MountViolationType.BLOCKED_DEVICE,
            error_message=f"Mount path refers to a blocked character/block or system device: {trimmed}",
        )

    # 3. Dangerous system path check
    if not allow_dangerous_override and is_dangerous_path(trimmed):
        return MountValidationResult(
            is_valid=False,
            violation_type=MountViolationType.DANGEROUS_PATH,
            error_message=f"Mount source falls under a dangerous system or user root: {trimmed}",
        )

    # Resolve physical canonical path without altering virtual prefix when unnecessary
    try:
        resolved_src = _resolve_physical_path(trimmed)
    except Exception as e:
        return MountValidationResult(
            is_valid=False,
            violation_type=MountViolationType.PATH_TRAVERSAL,
            error_message=f"Path resolution failed for {trimmed}: {e}",
        )

    if not allow_dangerous_override and is_dangerous_path(resolved_src):
        return MountValidationResult(
            is_valid=False,
            violation_type=MountViolationType.DANGEROUS_PATH,
            error_message=f"Resolved mount source falls under a dangerous root: {resolved_src}",
        )

    # 5. Boundary enclosure check
    if allowed_boundaries:
        enclosed = any(
            _is_path_enclosed_in_boundary(resolved_src, b)
            for b in allowed_boundaries
            if b and b.strip()
        )
        if not enclosed:
            # Check if this is a symlink escape
            is_symlink = os.path.islink(os.path.expanduser(trimmed))
            violation = MountViolationType.SYMLINK_ESCAPE if is_symlink else MountViolationType.UNAUTHORIZED_BOUNDARY
            return MountValidationResult(
                is_valid=False,
                violation_type=violation,
                error_message=f"Mount source {resolved_src} is outside allowed boundaries: {allowed_boundaries}",
            )

    # 6. Mode enforcement / Least privilege
    effective_mode = spec.mode
    if require_write is True and spec.mode == MountMode.RO:
        return MountValidationResult(
            is_valid=False,
            violation_type=MountViolationType.PERMISSION_VIOLATION,
            error_message=f"Mount source requires write permission but is configured as read-only: {trimmed}",
        )

    # Preserve the normalized path (so /home/... isn't unnecessarily rewritten to /System/Volumes/Data/home/...)
    # while guaranteeing realpath validation passed
    normalized_src = os.path.normpath(os.path.expanduser(trimmed))

    sanitized = MountSpec(
        source_path=normalized_src,
        target_path=spec.target_path or normalized_src,
        mode=effective_mode,
        label=spec.label,
    )
    return MountValidationResult(is_valid=True, sanitized_spec=sanitized)


def validate_and_sanitize_mounts(
    mounts: tuple[MountSpec, ...] | list[MountSpec],
    *,
    allowed_boundaries: tuple[str, ...] = (),
    allow_dangerous_override: bool = False,
) -> tuple[MountSpec, ...]:
    """Validate a batch of MountSpecs and return sanitized, deduplicated valid specs."""
    valid_specs: list[MountSpec] = []
    seen: set[tuple[str, MountMode]] = set()

    for spec in mounts:
        result = validate_mount_spec(
            spec,
            allowed_boundaries=allowed_boundaries,
            allow_dangerous_override=allow_dangerous_override,
        )
        if result.is_valid and result.sanitized_spec:
            s = result.sanitized_spec
            key = (_normalize_case_for_os(s.source_path), s.mode)
            if key not in seen:
                seen.add(key)
                valid_specs.append(s)
        else:
            logger.warning(
                "SandboxMountSecurityGate rejected mount %s: %s (%s)",
                spec.source_path,
                result.error_message,
                result.violation_type,
            )

    return tuple(valid_specs)
