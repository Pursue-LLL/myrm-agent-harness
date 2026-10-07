# [POS]: tests.unit.toolkits.memory.test_tiered_consensus_suite
# [INPUT]: myrm_agent_harness.toolkits.memory (tiered_consensus models and manager)
# [OUTPUT]: Pytest unit test cases for tiered memory hierarchy and consensus flow

"""Unit tests for Tiered Memory Hierarchy and Proposed Consensus Flow Suite.

Validates scoping boundaries, idempotent deduplication, anti-self-approval gates,
safe retrieval filtering, and full lifecycle audit trails.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory import (
    ConsensusScopeTier,
    ProposalStatus,
    TieredConsensusManager,
    compute_content_fingerprint,
)


def test_fingerprint_normalization():
    """Verify deterministic hash fingerprint over casing and whitespace variations."""
    fp1 = compute_content_fingerprint("  Code Quality Rule: Single File Under 400 Lines  ")
    fp2 = compute_content_fingerprint("code quality rule: single file under 400 lines")
    assert fp1 == fp2
    assert len(fp1) == 16


def test_propose_tiered_records_and_scoping_rules():
    """Verify tier-specific auto-approval vs draft governance and project requirement."""
    mgr = TieredConsensusManager()

    # 1. Personal tier: Auto-approved immediately
    rec_personal = mgr.propose_record(
        scope_tier=ConsensusScopeTier.PERSONAL,
        content="Prefer pytest concise syntax without superfluous fixtures",
        owner_peer_id="user_developer",
    )
    assert rec_personal.status == ProposalStatus.APPROVED
    assert rec_personal.scope_tier == ConsensusScopeTier.PERSONAL
    assert rec_personal.project_id is None

    # 2. Project tier: Auto-approved for project, requires project_id
    with pytest.raises(ValueError, match="project_id is strictly required"):
        mgr.propose_record(
            scope_tier=ConsensusScopeTier.PROJECT,
            content="Use SQLite WAL mode for local concurrency",
            owner_peer_id="agent_coder",
            project_id=None,
        )

    rec_project = mgr.propose_record(
        scope_tier=ConsensusScopeTier.PROJECT,
        content="Use SQLite WAL mode for local concurrency",
        owner_peer_id="agent_coder",
        project_id="proj_alpha",
    )
    assert rec_project.status == ProposalStatus.APPROVED
    assert rec_project.project_id == "proj_alpha"

    # 3. Team consensus tier: Enforces proposed draft status
    rec_team = mgr.propose_record(
        scope_tier=ConsensusScopeTier.TEAM_CONSENSUS,
        content="All public API endpoints must return ApiResponse wrapper",
        owner_peer_id="agent_architect",
        rationale="Microservice standard alignment",
    )
    assert rec_team.status == ProposalStatus.PROPOSED
    assert rec_team.scope_tier == ConsensusScopeTier.TEAM_CONSENSUS

    # 4. Idempotent proposal deduplication
    rec_dup = mgr.propose_record(
        scope_tier=ConsensusScopeTier.TEAM_CONSENSUS,
        content="  ALL public API endpoints must return ApiResponse wrapper  ",
        owner_peer_id="agent_reviewer",
    )
    assert rec_dup.record_id == rec_team.record_id


def test_approval_flow_and_anti_self_approval_gate():
    """Verify owner approval and enforcement preventing agent self-approval."""
    mgr = TieredConsensusManager()

    rec = mgr.propose_record(
        scope_tier=ConsensusScopeTier.TEAM_CONSENSUS,
        content="Zero Any policy enforced across all Python type hints",
        owner_peer_id="agent_quality_bot",
    )
    assert rec.status == ProposalStatus.PROPOSED

    # Agent cannot self-approve its own proposal
    with pytest.raises(PermissionError, match="cannot self-approve"):
        mgr.approve_proposal(
            record_id=rec.record_id,
            approver_peer_id="agent_quality_bot",
            reason="I think my rule is great",
        )

    # Human user or lead administrator approves proposal
    approved_rec = mgr.approve_proposal(
        record_id=rec.record_id,
        approver_peer_id="user_admin",
        reason="Strict typing mandate ratified by engineering council",
    )
    assert approved_rec.status == ProposalStatus.APPROVED

    # Cannot approve already approved record
    with pytest.raises(ValueError, match="Cannot approve record in status 'approved'"):
        mgr.approve_proposal(record_id=rec.record_id, approver_peer_id="user_admin")


def test_rejection_and_revocation_with_audit_trail():
    """Verify proposal rejection, consensus revocation with supersession, and immutable audit logs."""
    mgr = TieredConsensusManager()

    # 1. Reject proposal
    rec_draft = mgr.propose_record(
        scope_tier=ConsensusScopeTier.TEAM_CONSENSUS,
        content="Deprecated rule: write raw SQL queries in route handlers",
        owner_peer_id="agent_junior",
    )
    rejected = mgr.reject_proposal(
        record_id=rec_draft.record_id,
        approver_peer_id="user_tech_lead",
        reason="Security violation: SQL injection risk",
    )
    assert rejected.status == ProposalStatus.REJECTED

    # 2. Revoke previously approved consensus with supersession link
    rec_old = mgr.propose_record(
        scope_tier=ConsensusScopeTier.PERSONAL,
        content="Legacy formatting rule",
        owner_peer_id="user_developer",
    )
    revoked = mgr.revoke_consensus(
        record_id=rec_old.record_id,
        operator_peer_id="user_developer",
        reason="Superseded by Ruff formatter standard",
        superseded_by="mem_tier_new_001",
    )
    assert revoked.status == ProposalStatus.REVOKED
    assert revoked.superseded_by == "mem_tier_new_001"

    # 3. Verify audit trail
    audits = mgr.get_audit_trail(rec_old.record_id)
    assert len(audits) >= 2
    actions = [a.action for a in audits]
    assert "propose" in actions
    assert "revoke" in actions


def test_safe_query_filtering_prevents_leakage():
    """Verify default query filtering strictly hides unapproved proposed drafts in team consensus."""
    mgr = TieredConsensusManager()

    mgr.propose_record(
        scope_tier=ConsensusScopeTier.TEAM_CONSENSUS,
        content="Unvetted draft guideline: use global mutable state for caching",
        owner_peer_id="agent_hacker",
    )
    rec_approved = mgr.propose_record(
        scope_tier=ConsensusScopeTier.TEAM_CONSENSUS,
        content="Approved guideline: use Redis or Qdrant for external cache",
        owner_peer_id="user_architect",
    )
    mgr.approve_proposal(record_id=rec_approved.record_id, approver_peer_id="user_lead")

    # Default query hides proposed draft
    safe_results = mgr.query_records(scope_tier=ConsensusScopeTier.TEAM_CONSENSUS)
    assert len(safe_results) == 1
    assert safe_results[0].record_id == rec_approved.record_id

    # Explicit query including proposed shows both
    admin_results = mgr.query_records(
        scope_tier=ConsensusScopeTier.TEAM_CONSENSUS,
        include_proposed=True,
    )
    assert len(admin_results) == 2
