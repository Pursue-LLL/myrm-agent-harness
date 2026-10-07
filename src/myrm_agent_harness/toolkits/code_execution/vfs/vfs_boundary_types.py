"""VFS boundary types, contracts, and safety audit models.

Defines path classification kinds, glob safety configurations, hit records
with explicit trailing slash indicators, and traversal safety audits.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- VFSPathKind: Filesystem path item classification.
- GlobBoundaryViolationError: Raised when glob pattern or path traversal breaches security boundaries.
- GlobSafetyConfig: Configuration governing recursive glob boundaries and traversal safety.
- VFSGlobHit: Standardized result entry from a boundary-enforced glob traversal.
- GlobSafetyAudit: Security and performance diagnostic audit for a glob execution run.

[POS]
VFS boundary types, contracts, and safety audit models.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VFSPathKind(StrEnum):
    """Filesystem path item classification."""

    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    SPECIAL = "special"


class GlobBoundaryViolationError(Exception):
    """Raised when glob pattern or path traversal breaches security boundaries."""


@dataclass(frozen=True)
class GlobSafetyConfig:
    """Configuration governing recursive glob boundaries and traversal safety."""

    max_depth: int = 10
    max_results: int = 500
    follow_symlinks: bool = False
    require_trailing_slash_for_dirs: bool = True
    ignore_hidden: bool = False


@dataclass(frozen=True)
class VFSGlobHit:
    """Standardized result entry from a boundary-enforced glob traversal."""

    path: str
    raw_name: str
    kind: VFSPathKind
    depth: int
    is_directory: bool
    has_trailing_slash: bool


@dataclass(frozen=True)
class GlobSafetyAudit:
    """Security and performance diagnostic audit for a glob execution run."""

    root_directory: str
    pattern: str
    total_scanned: int
    matched_count: int
    truncated_by_depth: bool
    truncated_by_limit: bool
    symlink_cycles_detected: int
    traversal_violations: int
