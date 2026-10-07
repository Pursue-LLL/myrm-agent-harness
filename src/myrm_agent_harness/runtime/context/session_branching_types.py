from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RewindMode(StrEnum):
    """Execution mode for timeline rewind."""

    IN_PLACE_TRUNCATE = "in_place_truncate"
    STAGING_BRANCH = "staging_branch"


@dataclass(frozen=True, slots=True)
class BranchHistoricalTurn:
    """Historical conversation turn entry for branch replay."""

    message_id: str
    role: str
    content: str
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    created_at_ms: int = 0


@dataclass(frozen=True, slots=True)
class BranchDescriptor:
    """Descriptor defining a session branch and its topological lineage."""

    session_id: str
    branch_name: str
    parent_session_id: str | None
    fork_point_message_id: str | None
    fork_point_turn_index: int
    created_at_ms: int
    workspace_root: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ForkSessionResult:
    """Outcome of forking a session from a specific history checkpoint."""

    new_session_id: str
    branch_descriptor: BranchDescriptor
    cloned_turns: list[BranchHistoricalTurn]


@dataclass(frozen=True, slots=True)
class RewindSessionResult:
    """Outcome of rewinding a session timeline to a target message."""

    session_id: str
    mode: RewindMode
    target_message_id: str
    active_turns: list[BranchHistoricalTurn]
    truncated_turns: list[BranchHistoricalTurn]
    created_staging_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class BranchNavigatorView:
    """Data payload for frontend multi-branch visual switcher (e.g., Branch 1/3)."""

    current_session_id: str
    current_branch_name: str
    total_sibling_branches: int
    current_sibling_index: int
    sibling_branches: list[BranchDescriptor]
    parent_session_id: str | None
    children_branches: list[BranchDescriptor]
