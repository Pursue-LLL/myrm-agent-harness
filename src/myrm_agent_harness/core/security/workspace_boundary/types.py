"""Domain types and models for Workspace File Access Boundary Guard & Actual Path Link Resolver.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing file access verdicts, actions,
  boundary policies, and path resolution results.

[POS]
- Harness core domain models ensuring desktop chat links and agent file actions
  strictly adhere to workspace boundaries and prevent symlink escape or path traversal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FileAccessVerdict(StrEnum):
    """Access determination for workspace file operations."""

    ALLOWED = "ALLOWED"
    REFUSED_OUTSIDE_WORKSPACE = "REFUSED_OUTSIDE_WORKSPACE"
    REFUSED_SYMLINK_ESCAPE = "REFUSED_SYMLINK_ESCAPE"
    REFUSED_MISSING = "REFUSED_MISSING"
    REFUSED_NOT_FILE = "REFUSED_NOT_FILE"
    REFUSED_INVALID_PATH = "REFUSED_INVALID_PATH"


class FileActionType(StrEnum):
    """File actions subject to boundary guard enforcement."""

    LAUNCH_DEFAULT_APP = "LAUNCH_DEFAULT_APP"
    REVEAL_IN_FOLDER = "REVEAL_IN_FOLDER"
    READ_CONTENT = "READ_CONTENT"
    EDIT_CONTENT = "EDIT_CONTENT"


@dataclass(frozen=True)
class WorkspaceBoundaryPolicy:
    """Configuration governing allowable workspace directory roots and symlink behavior."""

    workspace_roots: tuple[str, ...]
    allow_symlinks_within_root: bool = True
    disallow_external_symlinks: bool = True
    allowed_schemes: tuple[str, ...] = ("file", "")


@dataclass(frozen=True)
class PathResolutionResult:
    """Outcome of resolving a link or path to its physical location on disk."""

    raw_input: str
    resolved_physical_path: str | None
    workspace_root: str
    verdict: FileAccessVerdict
    is_inside_workspace: bool
    is_regular_file: bool
    can_launch: bool
    can_reveal: bool
    can_read: bool
    error_message: str = ""


class WorkspaceBoundaryError(Exception):
    """Base exception for workspace boundary and path resolution failures."""


class SymlinkEscapeError(WorkspaceBoundaryError):
    """Raised when a symlink resolves to a target outside the workspace root."""


class PathTraversalError(WorkspaceBoundaryError):
    """Raised when a path uses traversal sequences to escape workspace boundaries."""
