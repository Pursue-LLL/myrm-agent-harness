# [POS] tests/toolkits/memory/test_conflict_arbitration.py
# [INPUT] pytest, myrm_agent_harness.toolkits.memory.conflict_arbitration
# [OUTPUT] TestConflictArbitrationSuite

import pytest

from myrm_agent_harness.toolkits.memory.conflict_arbitration import (
    ConflictResolutionKind,
    HumanArbitrationDecision,
    MemorySemanticArbitrator,
    UserConfirmedFreezeGate,
    UserConfirmedFreezeLock,
    UserConfirmedFreezeViolationError,
)


def test_user_confirmed_freeze_lock_integrity() -> None:
    """Validate that UserConfirmedFreezeLock computes and verifies cryptographic hash correctly."""
    lock = UserConfirmedFreezeLock(
        memory_id="mem-101",
        frozen_content="Use PostgreSQL for primary store.",
        confirmed_by="architect_alice",
        is_active=True,
        lock_version=1,
    )
    assert lock.immutable_hash != ""
    assert lock.verify_integrity() is True

    # Tampered instance verification failure
    tampered_lock = UserConfirmedFreezeLock(
        memory_id="mem-101",
        frozen_content="Use MongoDB instead.",
        confirmed_by="architect_alice",
        is_active=True,
        lock_version=1,
        immutable_hash=lock.immutable_hash,
    )
    assert tampered_lock.verify_integrity() is False


def test_freeze_gate_blocks_automated_mutations_and_allows_human_override() -> None:
    """Ensure freeze gate strictly blocks automated writes on frozen items but permits human override."""
    gate = UserConfirmedFreezeGate()
    assert gate.is_frozen("mem-001") is False

    # Freeze the fact
    lock = gate.freeze(
        memory_id="mem-001",
        content="Production deployment must be air-gapped.",
        confirmed_by="security_officer_bob",
    )
    assert gate.is_frozen("mem-001") is True
    assert "mem-001" in gate.list_frozen_memory_ids()
    assert lock.verify_integrity() is True

    # Automated mutation attempt MUST raise UserConfirmedFreezeViolationError
    with pytest.raises(UserConfirmedFreezeViolationError) as exc_info:
        gate.check_mutation_allowed(
            memory_id="mem-001",
            proposed_content="Deploy to public multi-tenant cloud.",
            is_human_override=False,
        )
    assert exc_info.value.memory_id == "mem-001"
    assert "Automated overwrite is forbidden" in exc_info.value.reason

    # Human override attempt succeeds
    gate.check_mutation_allowed(
        memory_id="mem-001",
        proposed_content="Deploy to VPC private subnet with strict security groups.",
        is_human_override=True,
    )

    # Human explicit unlock
    unlocked = gate.unlock(
        memory_id="mem-001",
        operator_id="admin_charlie",
        reason="Approved architectural policy revision",
    )
    assert unlocked is True
    assert gate.is_frozen("mem-001") is False

    # Once unlocked, automated mutations are allowed
    gate.check_mutation_allowed(
        memory_id="mem-001",
        proposed_content="Updated deployment spec.",
        is_human_override=False,
    )


def test_semantic_arbitrator_override_and_merge_detection() -> None:
    """Test that explicit override and merge heuristics categorize correctly."""
    arbitrator = MemorySemanticArbitrator()

    # 1. Explicit override
    rec_override = arbitrator.detect_conflict_between_facts(
        conflict_id="conf-1",
        entity_key="project_deadline",
        attribute_name="target_date",
        existing_memory_id="mem-d1",
        existing_fact_text="项目截止时间为2026年10月1日",
        candidate_fact_text="经管理层讨论，截止时间更正为2026年10月20日",
        is_existing_frozen=False,
    )
    assessment_override = arbitrator.evaluate_conflict(rec_override)
    assert assessment_override.resolution_kind == ConflictResolutionKind.OVERRIDE
    assert assessment_override.requires_human_confirmation is False
    assert "更正为" in assessment_override.reasoning

    # 2. Additive merge
    rec_merge = arbitrator.detect_conflict_between_facts(
        conflict_id="conf-2",
        entity_key="backend_stack",
        attribute_name="cache",
        existing_memory_id="mem-c1",
        existing_fact_text="缓存采用Redis Cluster",
        candidate_fact_text="同时采用本地LRU内存缓存加速高频只读请求",
        is_existing_frozen=False,
    )
    assessment_merge = arbitrator.evaluate_conflict(rec_merge)
    assert assessment_merge.resolution_kind == ConflictResolutionKind.MERGE
    assert assessment_merge.requires_human_confirmation is False
    assert "同时采用本地LRU" in assessment_merge.suggested_text


def test_semantic_arbitrator_contradiction_and_freeze_blocked() -> None:
    """Test that contradictory facts require human confirmation and frozen memories trigger FREEZE_BLOCKED."""
    arbitrator = MemorySemanticArbitrator()

    # 1. Direct contradiction with no override syntax -> CONTRADICTION, requires human review
    rec_contra = arbitrator.detect_conflict_between_facts(
        conflict_id="conf-3",
        entity_key="database_choice",
        attribute_name="engine",
        existing_memory_id="mem-db1",
        existing_fact_text="必须使用PostgreSQL作为唯一持久化数据库",
        candidate_fact_text="使用MongoDB作为主要文档数据库",
        is_existing_frozen=False,
    )
    assessment_contra = arbitrator.evaluate_conflict(rec_contra)
    assert assessment_contra.resolution_kind == ConflictResolutionKind.CONTRADICTION
    assert assessment_contra.requires_human_confirmation is True

    # 2. Conflict against frozen memory -> FREEZE_BLOCKED
    rec_frozen = arbitrator.detect_conflict_between_facts(
        conflict_id="conf-4",
        entity_key="database_choice",
        attribute_name="engine",
        existing_memory_id="mem-db1",
        existing_fact_text="必须使用PostgreSQL作为唯一持久化数据库",
        candidate_fact_text="使用MongoDB作为主要文档数据库",
        is_existing_frozen=True,
    )
    assessment_frozen = arbitrator.evaluate_conflict(rec_frozen)
    assert assessment_frozen.resolution_kind == ConflictResolutionKind.FREEZE_BLOCKED
    assert assessment_frozen.requires_human_confirmation is True
    assert assessment_frozen.confidence == 1.0


def test_human_arbitration_decision_and_freeze_workflow() -> None:
    """Verify end-to-end flow from human arbitration decision to immutable lock."""
    gate = UserConfirmedFreezeGate()
    arbitrator = MemorySemanticArbitrator()

    # Ambiguous conflicting update
    rec = arbitrator.detect_conflict_between_facts(
        conflict_id="conf-100",
        entity_key="cluster_auth",
        attribute_name="auth_mode",
        existing_memory_id="mem-auth-1",
        existing_fact_text="Cluster uses mTLS with SPIFFE/SPIRE IDs",
        candidate_fact_text="Cluster uses static API keys in Authorization header",
        is_existing_frozen=False,
    )
    assessment = arbitrator.evaluate_conflict(rec)
    assert assessment.requires_human_confirmation is True

    # Human operator reviews card and confirms Fact A with freeze lock
    human_decision = HumanArbitrationDecision(
        conflict_id="conf-100",
        chosen_resolution=ConflictResolutionKind.OVERRIDE,
        final_fact_text="Cluster strictly enforces mTLS with SPIFFE IDs, zero static API keys.",
        operator_id="ciso_david",
        should_freeze_lock=True,
        comment="Confirmed by architecture committee meeting on Oct 6.",
    )
    assert human_decision.should_freeze_lock is True

    # Apply decision to gate
    freeze_lock = gate.freeze(
        memory_id="mem-auth-1",
        content=human_decision.final_fact_text,
        confirmed_by=human_decision.operator_id,
    )
    assert freeze_lock.verify_integrity() is True
    assert gate.is_frozen("mem-auth-1") is True

    # Subsequent automated attempt to change to static tokens is intercepted
    with pytest.raises(UserConfirmedFreezeViolationError):
        gate.check_mutation_allowed(
            memory_id="mem-auth-1",
            proposed_content="Use static tokens for ease of development.",
            is_human_override=False,
        )
