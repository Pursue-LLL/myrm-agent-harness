"""Cross-surface agent activity ingress and presence projection types.

Supports streaming activities from Tauri desktop, CLI tools, cron runners, and
remote offices into Fleet Canvas without full transcript mirroring.

[INPUT]
- __future__
- time
- dataclasses
- typing

[OUTPUT]
- SurfaceOrigin
- ActivityKind
- PresenceStatus
- IngressActivityItem
- SurfacePresenceSummary
- CrossSurfaceProjectionSnapshot

[POS]
Cross-surface agent activity ingress and presence projection types.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

SurfaceOrigin = Literal[
    "tauri_desktop",
    "cli_tool",
    "cron_job",
    "remote_office_clone",
]

ActivityKind = Literal[
    "turn_start",
    "thinking_pulse",
    "tool_call",
    "tool_result",
    "turn_complete",
    "heartbeat",
]

PresenceStatus = Literal[
    "active",
    "idle",
    "completed",
]


@dataclass(frozen=True)
class IngressActivityItem:
    """Bounded, redacted activity event ingressed from an external surface."""

    activity_id: str
    session_key: str
    source_surface: SurfaceOrigin
    agent_id: str
    activity_kind: ActivityKind
    preview_text: str  # Bounded short preview <= 256 chars
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class SurfacePresenceSummary:
    """Read-only presence metadata for an external active surface session."""

    session_key: str
    source_surface: SurfaceOrigin
    agent_id: str
    status: PresenceStatus
    last_active_at: float
    recent_activities_count: int = 0


@dataclass
class CrossSurfaceProjectionSnapshot:
    """Snapshot representing recent projected external activities and presence list."""

    chat_id: str
    active_presences: list[SurfacePresenceSummary]
    total_ingressed_activities: int
    bounded_recent_activities: list[IngressActivityItem]
    last_ingressed_at: float | None = None
