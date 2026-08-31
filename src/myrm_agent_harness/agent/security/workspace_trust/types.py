"""Workspace trust level types for folder-side-channel execution gate."""

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
