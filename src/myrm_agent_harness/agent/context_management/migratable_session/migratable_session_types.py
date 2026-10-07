"""Strongly typed contracts for Decoupled Migratable Session and Hot-Seed Workspace Suite (Item 224).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- SessionLocationKind: Topological execution locus (local daemon, paired peer device, cloud worker).
- SessionAccessRole: Collaborative role permissions (view only, suggestor, full operator).
- SessionLiveStatus: Lifecycle state of a migratable session resource.
- WorkspaceHotSeedSpec: Sandboxed volume and filesystem state ready for instant container reuse.
- MigratableSessionBundle: First-class migratable session object carrying state, diffs, and environment.
- SessionForkOutcome: Result of time-travel branching at an arbitrary message checkpoint.
- SessionShareGrant: Scoped authorization credential enabling multi-user session collaboration.
- MigratableSessionConfig: Configuration parameters governing location dispatch and access control.

[POS]
- Transforms sessions from in-process Gateway state into addressable, migratable, forkable,
- and shareable resources inspired by OpenClaw 2.0 'Sessions beyond your Gateway'.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class SessionLocationKind(str, enum.Enum):
    """Topological placement of the session and its execution sandbox."""

    LOCAL_DAEMON = "local_daemon"
    PAIRED_DEVICE = "paired_device"
    CLOUD_SANDBOX_WORKER = "cloud_sandbox_worker"


class SessionAccessRole(str, enum.Enum):
    """Granular collaboration authorization levels."""

    VIEW_ONLY = "view_only"
    SUGGESTOR = "suggestor"
    FULL_OPERATOR = "full_operator"


class SessionLiveStatus(str, enum.Enum):
    """Execution lifecycle status of an addressable session resource."""

    ACTIVE_RUNNING = "active_running"
    IDLE_SUSPENDED = "idle_suspended"
    MIGRATING_IN_FLIGHT = "migrating_in_flight"
    COMPLETED = "completed"


@dataclass(slots=True)
class WorkspaceHotSeedSpec:
    """Packaged workspace state ensuring instantaneous hot-seed sandbox container reuse."""

    volume_id: str
    working_dir: str
    git_commit_sha: str | None = None
    uncommitted_diff: str | None = None
    env_vars: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serializes workspace hot-seed specification to dictionary."""
        return {
            "volume_id": self.volume_id,
            "working_dir": self.working_dir,
            "git_commit_sha": self.git_commit_sha,
            "uncommitted_diff": self.uncommitted_diff,
            "env_vars": dict(self.env_vars),
        }


@dataclass(slots=True)
class MigratableSessionBundle:
    """First-class addressable session resource carrying context, workspace volume, and environment."""

    session_id: str
    title: str
    location: SessionLocationKind
    live_status: SessionLiveStatus
    hot_seed: WorkspaceHotSeedSpec
    created_at: float = field(default_factory=time.time)
    active_turn_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serializes session bundle to dictionary."""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "location": self.location.value,
            "live_status": self.live_status.value,
            "hot_seed": self.hot_seed.to_dict(),
            "created_at": self.created_at,
            "active_turn_id": self.active_turn_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class SessionForkOutcome:
    """Outcome of branching a session at an arbitrary message checkpoint."""

    original_session_id: str
    forked_session_id: str
    fork_point_message_id: str
    forked_turns_count: int
    branched_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes fork outcome to dictionary."""
        return {
            "original_session_id": self.original_session_id,
            "forked_session_id": self.forked_session_id,
            "fork_point_message_id": self.fork_point_message_id,
            "forked_turns_count": self.forked_turns_count,
            "branched_at": self.branched_at,
        }


@dataclass(slots=True)
class SessionShareGrant:
    """Security authorization ticket granting role-based collaborative session access."""

    share_token: str
    session_id: str
    role: SessionAccessRole
    granted_to_user_id: str | None = None
    expires_at: float | None = None
    is_active: bool = True
    created_at: float = field(default_factory=time.time)

    def is_expired(self, as_of: float | None = None) -> bool:
        """Checks whether this share grant has lapsed."""
        if not self.is_active:
            return True
        if self.expires_at is None:
            return False
        now = as_of if as_of is not None else time.time()
        return now > self.expires_at

    def to_dict(self) -> dict[str, object]:
        """Serializes share grant to dictionary."""
        return {
            "share_token": self.share_token,
            "session_id": self.session_id,
            "role": self.role.value,
            "granted_to_user_id": self.granted_to_user_id,
            "expires_at": self.expires_at,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class MigratableSessionConfig:
    """Configuration governing session migration, hot seeds, and share permissions."""

    default_location: SessionLocationKind = SessionLocationKind.LOCAL_DAEMON
    allow_forking: bool = True
    token_validity_hours: float = 72.0
    enable_env_var_sanitization: bool = True
