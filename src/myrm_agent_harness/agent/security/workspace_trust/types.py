"""Workspace trust level types for folder-side-channel execution gate.

[INPUT]
- None (plain value objects constructed by callers)

[OUTPUT]
- WorkspaceTrustLevel: TRUSTED / RESTRICTED / REVOKED user decision
- WorkspaceTrustManifest: pre-bind disclosure payload
- WorkspaceTrustEntry: persisted registry row for one canonical root

[POS]
Leaf type module of the workspace_trust gate. Frozen dataclasses and one str-Enum, so the
values are hashable and safe to pass across the async run boundary. No I/O and no imports
from sibling modules, which keeps this module the dependency root of the package.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkspaceTrustLevel(str, Enum):
    """User decision for a canonical workspace root."""

    TRUSTED = "TRUSTED"
    RESTRICTED = "RESTRICTED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class WorkspaceTrustManifest:
    """Pre-bind disclosure payload shown before the user trusts a folder."""

    path: str
    canonical_path: str
    skill_count: int = 0
    rule_count: int = 0
    repo_command_prefixes: tuple[str, ...] = ()
    has_myrm_config: bool = False
    current_level: WorkspaceTrustLevel | None = None


@dataclass(frozen=True)
class WorkspaceTrustEntry:
    """Persisted registry row for one canonical workspace root."""

    path: str
    level: WorkspaceTrustLevel
    decided_at: str
    manifest_hash: str = ""
