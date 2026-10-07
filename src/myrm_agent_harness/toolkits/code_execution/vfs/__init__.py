"""VFS and sandbox boundary enforcer package.

Provides unambiguous directory delineation with trailing slashes,
glob recursive depth limits, and sandbox boundary protection.

[INPUT]
- toolkits.code_execution.vfs.glob_boundary_enforcer::GlobBoundaryEnforcer (POS: Glob boundary enforcer for
  safe, cycle-free, and depth-governed filesystem traversal.)
- toolkits.code_execution.vfs.trailing_slash_delineator::TrailingSlashDelineator (POS: Trailing slash
  directory delineator for unambiguous filesystem path contracts.)
- toolkits.code_execution.vfs.vfs_boundary_types::GlobBoundaryViolationError, GlobSafetyAudit,
  GlobSafetyConfig, VFSGlobHit, VFSPathKind (POS: VFS boundary types, contracts, and safety audit models.)

[OUTPUT]
- Package facade re-exporting 7 public names: VFSPathKind, GlobBoundaryViolationError, GlobSafetyConfig,
  VFSGlobHit, GlobSafetyAudit, TrailingSlashDelineator, GlobBoundaryEnforcer

[POS]
VFS and sandbox boundary enforcer package.
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
