"""
[POS] tests/unit/test_readonly_research_sandbox_suite.py
[INPUT] myrm_agent_harness.core.security.readonly_research_sandbox
[OUTPUT] Unit test suite for Read-Only Autonomous Research Lease & Immutable Snapshot Sandbox

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.readonly_research_sandbox import (
    EphemeralCowOverlay,
    LeaseStatusEnum,
    ReadOnlyLeaseManager,
    ReadOnlyResearchSandboxFacade,
    ResearchModeEnum,
)


def test_readonly_lease_manager_lifecycle_and_tool_stripping() -> None:
    """Test read-only lease granting, tool physical stripping, revocation, and expiration."""
    mgr = ReadOnlyLeaseManager(default_ttl_seconds=10.0)
    session_id = "sess-lease-01"

    # 1. Grant lease
    lease = mgr.grant_lease(session_id, ResearchModeEnum.AUTONOMOUS_RESEARCH)
    assert lease.status == LeaseStatusEnum.ACTIVE
    assert lease.research_mode == ResearchModeEnum.AUTONOMOUS_RESEARCH

    # 2. Safe read tools pass
    allowed_r, _ = mgr.evaluate_tool(session_id, "read_file")
    assert allowed_r is True
    allowed_w_search, _ = mgr.evaluate_tool(session_id, "web_search")
    assert allowed_w_search is True

    # 3. Destructive side-effects are physically stripped
    allowed_w, reason_w = mgr.evaluate_tool(session_id, "write_file")
    assert allowed_w is False
    assert "physically stripped by Read-Only Research Lease" in reason_w

    allowed_s, reason_s = mgr.evaluate_tool(session_id, "shell_exec")
    assert allowed_s is False
    assert "physically stripped" in reason_s

    # 4. Unknown non-whitelisted tool blocked
    allowed_u, _ = mgr.evaluate_tool(session_id, "arbitrary_custom_mutator")
    assert allowed_u is False

    # 5. Revoke lease
    rev_lease = mgr.revoke_lease(session_id)
    assert rev_lease is not None
    assert rev_lease.status == LeaseStatusEnum.REVOKED

    # Once revoked, standard dispatch permitted
    allowed_post, _ = mgr.evaluate_tool(session_id, "write_file")
    assert allowed_post is True

    # 6. Expiration test
    mgr.grant_lease("sess-exp", ResearchModeEnum.BACKGROUND_STUDY, ttl_seconds=0.01)
    exp_lease = mgr.get_lease("sess-exp", current_time=time.time() + 100)
    assert exp_lease is not None
    assert exp_lease.status == LeaseStatusEnum.EXPIRED


def test_ephemeral_cow_overlay_snapshot_and_purity() -> None:
    """Test immutable snapshot baseline, purity verification, and in-memory CoW overlay purge."""
    overlay = EphemeralCowOverlay()
    session_id = "sess-cow-01"
    baseline = {
        "src/main.py": "print('hello')",
        "config.json": '{"env": "prod"}',
    }

    # 1. Take baseline snapshot
    snap = overlay.take_snapshot(session_id, baseline)
    assert len(snap.root_digest) == 64
    assert snap.file_manifest_hashes["src/main.py"] is not None

    # 2. Baseline purity matches
    is_pure, _ = overlay.verify_workspace_purity(session_id, baseline)
    assert is_pure is True

    # 3. Pollution detected if real workspace is modified
    polluted = dict(baseline)
    polluted["unauthorized_dump.txt"] = "malicious payload"
    is_pure_p, reason_p = overlay.verify_workspace_purity(session_id, polluted)
    assert is_pure_p is False
    assert "Pollution detected: 1 added" in reason_p

    # 4. Transient in-memory CoW output writes do not pollute base
    rec = overlay.write_ephemeral_file(session_id, "charts/analysis.png", b"\x89PNG\r\n\x1a\n")
    assert rec.virtual_path == "charts/analysis.png"
    assert overlay.read_ephemeral_file(session_id, "charts/analysis.png") == b"\x89PNG\r\n\x1a\n"
    assert len(overlay.list_ephemeral_files(session_id)) == 1

    # 5. Purge overlay on completion
    purged_count = overlay.purge_overlay(session_id)
    assert purged_count == 1
    assert len(overlay.list_ephemeral_files(session_id)) == 0


def test_facade_end_to_end_and_badge_metrics() -> None:
    """Test facade end-to-end lease enforcement, badge generation, and metrics."""
    facade = ReadOnlyResearchSandboxFacade()
    session_id = "sess-facade-ro"
    workspace = {"README.md": "# Research Study"}

    # 1. Take snapshot and grant lease
    facade.take_snapshot(session_id, workspace)
    lease = facade.grant_research_lease(session_id, ResearchModeEnum.AUTONOMOUS_RESEARCH)
    assert lease.status == LeaseStatusEnum.ACTIVE

    # 2. Verify shield badge
    badge = facade.get_shield_badge(session_id, workspace)
    assert badge.is_read_only_active is True
    assert badge.research_mode == ResearchModeEnum.AUTONOMOUS_RESEARCH
    assert badge.workspace_purity_verified is True
    assert "Read-Only Research Mode" in badge.badge_label

    # 3. Evaluate tool blocking and metrics
    allowed_w, _ = facade.evaluate_tool(session_id, "run_shell")
    assert allowed_w is False

    # 4. Ephemeral CoW write and badge cow_active flag
    facade.write_ephemeral_output(session_id, "temp_data.csv", "id,val\n1,10\n")
    badge_cow = facade.get_shield_badge(session_id)
    assert badge_cow.cow_overlay_active is True

    # 5. Purge overlay and verify purity
    purged = facade.purge_ephemeral_overlay(session_id)
    assert purged == 1

    is_pure, _ = facade.verify_workspace_purity(session_id, workspace)
    assert is_pure is True

    # 6. Metrics
    metrics = facade.get_metrics()
    assert metrics.total_leases_granted == 1
    assert metrics.active_leases_count == 1
    assert metrics.write_attempts_blocked == 1
    assert metrics.ephemeral_cow_files_staged == 1
    assert metrics.overlays_purged_count == 1
    assert metrics.purity_verifications_count >= 1
