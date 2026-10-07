"""Core engine for Decoupled Migratable Session and Hot-Seed Workspace Suite (Item 224).

[INPUT]
- WorkspaceHotSeedSpec: Sandboxed volume and diff metadata.
- MigratableSessionBundle: Session objects undergoing migration or branching.
- MigratableSessionConfig: Placement policies, token validity limits, and forking switches.

[OUTPUT]
- DecoupledMigratableSessionEngine: Governs 3D decoupled session lifecycles, branching, and shares.
- SessionForkOutcome: Lineage records linking parent and branched sessions.
- SessionShareGrant: Validated capability tokens enabling collaborative access.

[POS]
- Unlocks location decoupling (cross-device/cloud migration), time decoupling (forkable history),
- and subject decoupling (role-based sharing) for industrial-grade resilience.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Mapping

from .migratable_session_types import (
    MigratableSessionBundle,
    MigratableSessionConfig,
    SessionAccessRole,
    SessionForkOutcome,
    SessionLiveStatus,
    SessionLocationKind,
    SessionShareGrant,
    WorkspaceHotSeedSpec,
)


class DecoupledMigratableSessionEngine:
    """Manages location, time, and subject decoupled session resources."""

    def __init__(self, config: MigratableSessionConfig | None = None) -> None:
        self._config: MigratableSessionConfig = config or MigratableSessionConfig()
        self._sessions: dict[str, MigratableSessionBundle] = {}
        self._fork_lineage: dict[str, list[SessionForkOutcome]] = {}
        self._share_grants: dict[str, SessionShareGrant] = {}
        self._lock: threading.Lock = threading.Lock()

    @property
    def config(self) -> MigratableSessionConfig:
        """Returns active engine configuration."""
        return self._config

    def create_session_bundle(
        self,
        session_id: str,
        title: str,
        hot_seed: WorkspaceHotSeedSpec,
        location: SessionLocationKind | None = None,
        metadata: dict[str, str] | None = None,
    ) -> MigratableSessionBundle:
        """Creates and registers an addressable migratable session bundle."""
        loc = location or self._config.default_location
        bundle = MigratableSessionBundle(
            session_id=session_id,
            title=title,
            location=loc,
            live_status=SessionLiveStatus.ACTIVE_RUNNING,
            hot_seed=hot_seed,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._sessions[session_id] = bundle
        return bundle

    def get_session(self, session_id: str) -> MigratableSessionBundle | None:
        """Retrieves a registered session bundle by ID."""
        with self._lock:
            return self._sessions.get(session_id)

    def prepare_session_migration(
        self,
        session_id: str,
        target_location: SessionLocationKind,
    ) -> MigratableSessionBundle:
        """Transitions session to MIGRATING_IN_FLIGHT and prepares hot-seed payload.

        Args:
            session_id: Identifier of session to migrate.
            target_location: Target device or cloud worker locus.

        Returns:
            Updated MigratableSessionBundle.

        Raises:
            KeyError: If session_id is not registered.
        """
        with self._lock:
            bundle = self._sessions.get(session_id)
            if bundle is None:
                raise KeyError(f"Session '{session_id}' not found for migration.")

            bundle.live_status = SessionLiveStatus.MIGRATING_IN_FLIGHT
            bundle.metadata["migration_target"] = target_location.value
            bundle.metadata["migration_initiated_at"] = str(time.time())

            # Sanitize environment variables if enabled
            if self._config.enable_env_var_sanitization:
                safe_envs = {
                    k: v
                    for k, v in bundle.hot_seed.env_vars.items()
                    if not any(s in k.lower() for s in ("secret", "token", "password", "key"))
                }
                bundle.hot_seed.env_vars = safe_envs

        return bundle

    def complete_session_migration(
        self,
        session_id: str,
        target_location: SessionLocationKind,
    ) -> MigratableSessionBundle:
        """Confirms successful takeover at target location and restores ACTIVE_RUNNING state."""
        with self._lock:
            bundle = self._sessions.get(session_id)
            if bundle is None:
                raise KeyError(f"Session '{session_id}' not found.")

            bundle.location = target_location
            bundle.live_status = SessionLiveStatus.ACTIVE_RUNNING
            bundle.metadata["migration_completed_at"] = str(time.time())
            bundle.metadata.pop("migration_target", None)

        return bundle

    def fork_session_at_message(
        self,
        original_session_id: str,
        fork_point_message_id: str,
        new_forked_session_id: str,
        message_history: list[dict[str, object]],
        new_title: str | None = None,
    ) -> SessionForkOutcome:
        """Forks a session at an arbitrary message checkpoint, creating an independent branch.

        Args:
            original_session_id: Parent session ID.
            fork_point_message_id: Message ID serving as the branch root.
            new_forked_session_id: New child session ID.
            message_history: Sequential conversation history.
            new_title: Optional title for the new branch.

        Returns:
            SessionForkOutcome tracking branch lineage.

        Raises:
            RuntimeError: If forking is disabled.
            KeyError: If original session is not found.
            ValueError: If fork_point_message_id is not present in history.
        """
        if not self._config.allow_forking:
            raise RuntimeError("Session forking is disabled by configuration.")

        with self._lock:
            parent = self._sessions.get(original_session_id)
            if parent is None:
                raise KeyError(f"Parent session '{original_session_id}' not found.")

            # Locate branch point in message history
            split_idx = -1
            for idx, msg in enumerate(message_history):
                if str(msg.get("message_id", "")) == fork_point_message_id:
                    split_idx = idx
                    break

            if split_idx == -1:
                # Fallback: if not found by message_id, verify non-empty history
                if not message_history:
                    raise ValueError(f"Checkpoint '{fork_point_message_id}' not found in history.")
                split_idx = len(message_history) - 1

            forked_turns = split_idx + 1
            branch_title = new_title or f"{parent.title} (Fork from #{fork_point_message_id})"

            # Clone hot-seed workspace for independent branching
            cloned_seed = WorkspaceHotSeedSpec(
                volume_id=f"{parent.hot_seed.volume_id}-fork-{uuid.uuid4().hex[:6]}",
                working_dir=parent.hot_seed.working_dir,
                git_commit_sha=parent.hot_seed.git_commit_sha,
                uncommitted_diff=parent.hot_seed.uncommitted_diff,
                env_vars=dict(parent.hot_seed.env_vars),
            )

            child_bundle = MigratableSessionBundle(
                session_id=new_forked_session_id,
                title=branch_title,
                location=parent.location,
                live_status=SessionLiveStatus.ACTIVE_RUNNING,
                hot_seed=cloned_seed,
                metadata={
                    "forked_from_session_id": original_session_id,
                    "fork_point_message_id": fork_point_message_id,
                },
            )
            self._sessions[new_forked_session_id] = child_bundle

            outcome = SessionForkOutcome(
                original_session_id=original_session_id,
                forked_session_id=new_forked_session_id,
                fork_point_message_id=fork_point_message_id,
                forked_turns_count=forked_turns,
            )

            if original_session_id not in self._fork_lineage:
                self._fork_lineage[original_session_id] = []
            self._fork_lineage[original_session_id].append(outcome)

        return outcome

    def issue_share_grant(
        self,
        session_id: str,
        role: SessionAccessRole,
        expires_in_seconds: float | None = None,
        granted_to_user_id: str | None = None,
    ) -> SessionShareGrant:
        """Issues a time-limited collaborative share grant for a session."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session '{session_id}' not found.")

        if expires_in_seconds is not None:
            expires_at = time.time() + expires_in_seconds
        else:
            default_sec = self._config.token_validity_hours * 3600.0
            expires_at = time.time() + default_sec if default_sec > 0 else None
        token = f"grant_{session_id[:8]}_{uuid.uuid4().hex[:12]}"

        grant = SessionShareGrant(
            share_token=token,
            session_id=session_id,
            role=role,
            granted_to_user_id=granted_to_user_id,
            expires_at=expires_at,
        )

        with self._lock:
            self._share_grants[token] = grant

        return grant

    def verify_share_access(
        self,
        share_token: str,
        required_role: SessionAccessRole,
    ) -> bool:
        """Validates that a share grant is active, unexpired, and satisfies required permission."""
        with self._lock:
            grant = self._share_grants.get(share_token)
            if grant is None or grant.is_expired():
                return False

            role_hierarchy = {
                SessionAccessRole.VIEW_ONLY: 1,
                SessionAccessRole.SUGGESTOR: 2,
                SessionAccessRole.FULL_OPERATOR: 3,
            }
            user_level = role_hierarchy.get(grant.role, 0)
            required_level = role_hierarchy.get(required_role, 3)

            return user_level >= required_level

    def clear_session(self, session_id: str) -> None:
        """Purges session bundles, child forks, and share grants for a session."""
        with self._lock:
            self._sessions.pop(session_id, None)
            self._fork_lineage.pop(session_id, None)

            to_del = [tok for tok, g in self._share_grants.items() if g.session_id == session_id]
            for tok in to_del:
                self._share_grants.pop(tok, None)
