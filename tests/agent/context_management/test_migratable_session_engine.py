"""Unit tests for Decoupled Migratable Session and Hot-Seed Workspace Suite (Item 224).

[INPUT]
- DecoupledMigratableSessionEngine, MigratableSessionConfig, WorkspaceHotSeedSpec.
- Simulated multi-environment placements, time-travel history checkpoints, and collaboration roles.

[OUTPUT]
- Deterministic verification of location decoupling (cross-device/cloud migration with env sanitization),
- time decoupling (message-level tree forking), and subject decoupling (role-based capability sharing).

[POS]
- Verifies resilient session asset migration and collaboration without Gateway process lock-in.
"""

from __future__ import annotations

import time
import pytest

from myrm_agent_harness.agent.context_management.migratable_session import (
    DecoupledMigratableSessionEngine,
    MigratableSessionBundle,
    MigratableSessionConfig,
    SessionAccessRole,
    SessionForkOutcome,
    SessionLiveStatus,
    SessionLocationKind,
    SessionShareGrant,
    WorkspaceHotSeedSpec,
)


def test_session_bundle_creation_and_location_migration() -> None:
    """Verifies location decoupling lifecycle: local daemon creation, flight prep, and cloud takeover."""
    engine = DecoupledMigratableSessionEngine()

    hot_seed = WorkspaceHotSeedSpec(
        volume_id="vol-sandbox-dev-001",
        working_dir="/workspace/repo",
        git_commit_sha="a1b2c3d4e5",
        uncommitted_diff="M src/server.py",
        env_vars={"NODE_ENV": "development", "API_SECRET_TOKEN": "super_secret_123"},
    )

    bundle = engine.create_session_bundle(
        session_id="sess_mig_001",
        title="Long-Running Build & Test",
        hot_seed=hot_seed,
        location=SessionLocationKind.LOCAL_DAEMON,
    )

    assert bundle.session_id == "sess_mig_001"
    assert bundle.live_status == SessionLiveStatus.ACTIVE_RUNNING
    assert bundle.location == SessionLocationKind.LOCAL_DAEMON

    # Step 1: Prepare migration to cloud sandbox worker
    in_flight = engine.prepare_session_migration(
        session_id="sess_mig_001",
        target_location=SessionLocationKind.CLOUD_SANDBOX_WORKER,
    )
    assert in_flight.live_status == SessionLiveStatus.MIGRATING_IN_FLIGHT
    # Verify environment sanitization stripped sensitive key
    assert "API_SECRET_TOKEN" not in in_flight.hot_seed.env_vars
    assert in_flight.hot_seed.env_vars.get("NODE_ENV") == "development"

    # Step 2: Complete migration takeover on target cloud worker
    completed = engine.complete_session_migration(
        session_id="sess_mig_001",
        target_location=SessionLocationKind.CLOUD_SANDBOX_WORKER,
    )
    assert completed.live_status == SessionLiveStatus.ACTIVE_RUNNING
    assert completed.location == SessionLocationKind.CLOUD_SANDBOX_WORKER
    assert "migration_completed_at" in completed.metadata


def test_time_travel_session_forking() -> None:
    """Verifies time decoupling: branching independent sessions from arbitrary message checkpoints."""
    engine = DecoupledMigratableSessionEngine()

    hot_seed = WorkspaceHotSeedSpec(
        volume_id="vol-code-base-root",
        working_dir="/home/agent/workspace",
    )
    engine.create_session_bundle(
        session_id="sess_parent_main",
        title="Main Refactoring Workflow",
        hot_seed=hot_seed,
    )

    history = [
        {"message_id": "msg_001", "role": "user", "content": "Start project refactor"},
        {"message_id": "msg_002", "role": "assistant", "content": "Proposed plan A"},
        {"message_id": "msg_003", "role": "user", "content": "Execute plan A"},
    ]

    # Fork at checkpoint msg_002 to try Plan B
    fork_result = engine.fork_session_at_message(
        original_session_id="sess_parent_main",
        fork_point_message_id="msg_002",
        new_forked_session_id="sess_child_plan_b",
        message_history=history,
        new_title="Alternative Refactoring (Plan B)",
    )

    assert fork_result.original_session_id == "sess_parent_main"
    assert fork_result.forked_session_id == "sess_child_plan_b"
    assert fork_result.fork_point_message_id == "msg_002"
    assert fork_result.forked_turns_count == 2  # msg_001 and msg_002 included

    # Verify branched session was registered with cloned volume
    child_bundle = engine.get_session("sess_child_plan_b")
    assert child_bundle is not None
    assert "fork" in child_bundle.hot_seed.volume_id
    assert child_bundle.metadata["forked_from_session_id"] == "sess_parent_main"


def test_collaborative_share_grants_and_role_verification() -> None:
    """Verifies subject decoupling: time-limited role-based capability grants."""
    engine = DecoupledMigratableSessionEngine()

    hot_seed = WorkspaceHotSeedSpec(volume_id="vol-shared-review", working_dir="/app")
    engine.create_session_bundle(session_id="sess_collab_audit", title="Security Audit", hot_seed=hot_seed)

    # 1. Issue View-Only grant
    view_grant = engine.issue_share_grant(
        session_id="sess_collab_audit",
        role=SessionAccessRole.VIEW_ONLY,
        expires_in_seconds=3600,
    )
    assert view_grant.is_expired() is False
    assert engine.verify_share_access(view_grant.share_token, SessionAccessRole.VIEW_ONLY) is True
    # View-only should NOT satisfy Operator or Suggestor
    assert engine.verify_share_access(view_grant.share_token, SessionAccessRole.SUGGESTOR) is False
    assert engine.verify_share_access(view_grant.share_token, SessionAccessRole.FULL_OPERATOR) is False

    # 2. Issue Full Operator grant
    operator_grant = engine.issue_share_grant(
        session_id="sess_collab_audit",
        role=SessionAccessRole.FULL_OPERATOR,
        expires_in_seconds=3600,
    )
    # Operator satisfies all lower roles
    assert engine.verify_share_access(operator_grant.share_token, SessionAccessRole.VIEW_ONLY) is True
    assert engine.verify_share_access(operator_grant.share_token, SessionAccessRole.SUGGESTOR) is True
    assert engine.verify_share_access(operator_grant.share_token, SessionAccessRole.FULL_OPERATOR) is True

    # 3. Expired grant check
    expired_grant = engine.issue_share_grant(
        session_id="sess_collab_audit",
        role=SessionAccessRole.FULL_OPERATOR,
        expires_in_seconds=-10,  # Already expired
    )
    assert expired_grant.is_expired() is True
    assert engine.verify_share_access(expired_grant.share_token, SessionAccessRole.VIEW_ONLY) is False


def test_session_clear_and_not_found_guards() -> None:
    """Verifies error handling for unregistered sessions and clean teardown."""
    engine = DecoupledMigratableSessionEngine()

    with pytest.raises(KeyError, match="not found"):
        engine.prepare_session_migration("non_existent_sess", SessionLocationKind.CLOUD_SANDBOX_WORKER)

    hot_seed = WorkspaceHotSeedSpec(volume_id="vol-tmp", working_dir="/tmp")
    engine.create_session_bundle("sess_purge", "Temporary Session", hot_seed=hot_seed)
    grant = engine.issue_share_grant("sess_purge", SessionAccessRole.VIEW_ONLY)

    assert engine.get_session("sess_purge") is not None
    assert engine.verify_share_access(grant.share_token, SessionAccessRole.VIEW_ONLY) is True

    # Purge session
    engine.clear_session("sess_purge")
    assert engine.get_session("sess_purge") is None
    assert engine.verify_share_access(grant.share_token, SessionAccessRole.VIEW_ONLY) is False
