"""
[POS] src/myrm_agent_harness/core/security/blast_radius_approval/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] ImpactTargetType, ImpactPreviewTarget, DryRunImpactPreview, LaunchCodeRequirement, ApprovalSpanGroupPolicy
Domain types for Blast Radius Dry-Run Impact Preview & Typed Launch Codes Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ImpactTargetType(StrEnum):
    """Categorization of affected resources in blast radius evaluation."""

    FILE = "file"
    DIRECTORY = "directory"
    GIT_REF = "git_ref"
    DATABASE_TABLE = "database_table"
    CONTAINER = "container"


@dataclass(frozen=True)
class ImpactPreviewTarget:
    """Individual item affected by a destructive command execution."""

    path_or_identifier: str
    target_type: ImpactTargetType
    action: str = "delete"
    estimated_size_bytes: int | None = None


@dataclass(frozen=True)
class DryRunImpactPreview:
    """Pre-execution dry-run impact enumeration result."""

    command: str
    estimated_files_count: int
    estimated_dirs_count: int
    targets: tuple[ImpactPreviewTarget, ...]
    is_truncated: bool
    probe_duration_ms: float
    is_fallback_static: bool
    summary: str


@dataclass(frozen=True)
class LaunchCodeRequirement:
    """One-time challenge code or keyword required for high-risk irreversible actions."""

    requires_challenge: bool
    challenge_token: str | None = None
    expected_keyword: str | None = None
    expires_at: float | None = None
    is_used: bool = False
    prompt_message: str | None = None


@dataclass(frozen=True)
class ApprovalSpanGroupPolicy:
    """Approval metadata for individual spans in batch decision interrupts."""

    span_id: str
    command: str
    is_destructive: bool
    never_folded: bool
    impact_preview: DryRunImpactPreview | None
    launch_code: LaunchCodeRequirement | None
    allowed_shortcuts: tuple[str, ...] = ("Enter", "y", "Esc", "n")
