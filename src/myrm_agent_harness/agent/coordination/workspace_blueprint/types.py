"""Domain types and contracts for Per-Project Workspace Team Blueprint Auto-Reuse (Item 36).

[INPUT]
- Workspace identifiers, project keys, squad blueprints, and auto-reuse policy configurations.

[OUTPUT]
- Strongly-typed domain models for workspace-to-blueprint bindings, reuse resolutions,
  and snapshot metadata.

[POS]
- Harness coordination layer contracts for project team template auto-reuse.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class AutoReusePolicy(enum.StrEnum):
    """Policy governing when a bound team blueprint should be automatically instantiated."""

    ALWAYS_REUSE = "always_reuse"
    PROMPT_REUSE = "prompt_reuse"
    MANUAL_ONLY = "manual_only"


@dataclass(frozen=True)
class WorkspaceBlueprintBinding:
    """Persistent binding between a project workspace and an orchestrated squad blueprint."""

    workspace_id: str
    blueprint_id: str
    team_name: str
    auto_reuse_policy: AutoReusePolicy = AutoReusePolicy.PROMPT_REUSE
    bound_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    last_used_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    member_count: int = 0
    total_budget_tokens: int = 0
    project_label: str = ""
    blueprint_snapshot: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceBlueprintResolution:
    """Outcome of resolving a project workspace against registered team blueprints."""

    workspace_id: str
    binding: WorkspaceBlueprintBinding | None
    can_auto_instantiate: bool
    status_label: str
    resolution_rationale: str
