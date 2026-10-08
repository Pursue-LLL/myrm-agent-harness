"""Unit tests for Granular Workspace Path RBAC & Denial Audit in myrm-agent-harness."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.workspace_path_rbac import (
    FileActionType,
    GranularWorkspacePathGuard,
    PathAccessMode,
    PathRule,
    WorkspacePolicy,
    WriteDenialReason,
)


@pytest.fixture
def guard() -> GranularWorkspacePathGuard:
    g = GranularWorkspacePathGuard()
    policy = WorkspacePolicy(
        policy_id="policy_project_alpha",
        user_identity="alice@enterprise.corp",
        project_root="/workspace/alpha",
        rules=[
            PathRule(pattern="raw_data/*", mode=PathAccessMode.RO, description="Raw source inputs"),
            PathRule(pattern="config/*.yaml", mode=PathAccessMode.RO, description="Project config"),
            PathRule(pattern="deliverables/*", mode=PathAccessMode.RW, description="Deliverables output"),
        ],
        allowed_deliverables_dir="deliverables",
    )
    g.register_policy(policy)
    return g


def test_read_allowed_on_ro_and_rw_paths(guard: GranularWorkspacePathGuard) -> None:
    # 1. Read on RO path
    verdict_ro = guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_analyst",
        session_id="sess_001",
        user_identity="alice@enterprise.corp",
        relative_path="raw_data/dataset.csv",
        action=FileActionType.READ,
    )
    assert verdict_ro.allowed is True
    assert verdict_ro.effective_mode == PathAccessMode.RO

    # 2. Read on RW path
    verdict_rw = guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_analyst",
        session_id="sess_001",
        user_identity="alice@enterprise.corp",
        relative_path="deliverables/summary.pdf",
        action=FileActionType.READ,
    )
    assert verdict_rw.allowed is True
    assert verdict_rw.effective_mode == PathAccessMode.RW


def test_triple_write_denial_on_ro_path(guard: GranularWorkspacePathGuard) -> None:
    # 1. Attempt 1: Direct write / upload to RO path
    verdict_write = guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_analyst",
        session_id="sess_002",
        user_identity="alice@enterprise.corp",
        relative_path="raw_data/tampered.csv",
        action=FileActionType.DIRECT_WRITE,
    )
    assert verdict_write.allowed is False
    assert verdict_write.violation_reason == WriteDenialReason.READ_ONLY_PATH.value
    assert verdict_write.auto_reroute_hint is not None
    assert "deliverables/tampered.csv" in verdict_write.auto_reroute_hint
    assert verdict_write.denial_card is not None
    assert verdict_write.denial_card.blocked_path == "raw_data/tampered.csv"

    # 2. Attempt 2: Copy upload to RO path
    verdict_copy = guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_analyst",
        session_id="sess_002",
        user_identity="alice@enterprise.corp",
        relative_path="raw_data/copied_data.csv",
        action=FileActionType.COPY_WRITE,
    )
    assert verdict_copy.allowed is False
    assert verdict_copy.violation_reason == WriteDenialReason.READ_ONLY_PATH.value

    # 3. Attempt 3: Create directory in RO path
    verdict_mkdir = guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_analyst",
        session_id="sess_002",
        user_identity="alice@enterprise.corp",
        relative_path="raw_data/nested_dir",
        action=FileActionType.MKDIR,
    )
    assert verdict_mkdir.allowed is False
    assert verdict_mkdir.violation_reason == WriteDenialReason.READ_ONLY_PATH.value


def test_writes_allowed_on_deliverables_rw_path(
    guard: GranularWorkspacePathGuard,
) -> None:
    verdict_direct = guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_analyst",
        session_id="sess_003",
        user_identity="alice@enterprise.corp",
        relative_path="deliverables/chart.png",
        action=FileActionType.DIRECT_WRITE,
    )
    assert verdict_direct.allowed is True
    assert verdict_direct.effective_mode == PathAccessMode.RW

    verdict_mkdir = guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_analyst",
        session_id="sess_003",
        user_identity="alice@enterprise.corp",
        relative_path="deliverables/figures",
        action=FileActionType.MKDIR,
    )
    assert verdict_mkdir.allowed is True
    assert verdict_mkdir.effective_mode == PathAccessMode.RW


def test_audit_ledger_recording_and_stats(
    guard: GranularWorkspacePathGuard,
) -> None:
    # Perform 1 granted read and 2 denied writes
    guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_audited",
        session_id="sess_audit_01",
        user_identity="bob@enterprise.corp",
        relative_path="raw_data/info.txt",
        action=FileActionType.READ,
    )
    guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_audited",
        session_id="sess_audit_01",
        user_identity="bob@enterprise.corp",
        relative_path="raw_data/info.txt",
        action=FileActionType.DIRECT_WRITE,
    )
    guard.check_access_and_audit(
        policy_id="policy_project_alpha",
        agent_id="agent_audited",
        session_id="sess_audit_01",
        user_identity="bob@enterprise.corp",
        relative_path="config/settings.yaml",
        action=FileActionType.DELETE,
    )

    # Query audit ledger
    entries = guard.query_audit_ledger(session_id="sess_audit_01")
    assert len(entries) == 3

    denied_entries = guard.query_audit_ledger(
        session_id="sess_audit_01", granted=False
    )
    assert len(denied_entries) == 2

    # Stats
    stats = guard.get_audit_stats()
    assert stats["total_events"] >= 3
    assert stats["granted_count"] >= 1
    assert stats["denied_count"] >= 2
    assert "DIRECT_WRITE" in stats["denials_by_action"]
    assert "DELETE" in stats["denials_by_action"]
