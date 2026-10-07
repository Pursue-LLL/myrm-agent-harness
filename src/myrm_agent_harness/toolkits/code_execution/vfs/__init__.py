"""VFS and sandbox boundary enforcer package.

Provides unambiguous directory delineation with trailing slashes,
glob recursive depth limits, and sandbox boundary protection.
"""

from __future__ import annotations

from .glob_boundary_enforcer import GlobBoundaryEnforcer
from .trailing_slash_delineator import TrailingSlashDelineator
from .vfs_boundary_types import (
    GlobBoundaryViolationError,
    GlobSafetyAudit,
    GlobSafetyConfig,
    VFSGlobHit,
    VFSPathKind,
)

__all__ = [
    "VFSPathKind",
    "GlobBoundaryViolationError",
    "GlobSafetyConfig",
    "VFSGlobHit",
    "GlobSafetyAudit",
    "TrailingSlashDelineator",
    "GlobBoundaryEnforcer",
]
