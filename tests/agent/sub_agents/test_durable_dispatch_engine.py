"""[INPUT] Harness durable_dispatch submodule exports.
[OUTPUT] Unit tests verifying WorkContract dispatch, pre-start policy revalidation, bounded evidence admission, and idempotent crash recovery.
[POS] Unit tests for Hermes Fabric remote dispatch durable journal subsystem.
"""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.agent.sub_agents.durable_dispatch import (
    MAX_SINGLE_EVIDENCE_BYTES,
    DurableDispatchJournal,
    DurableRemoteDispatchEngine,
    EvidenceItem,
    JournalEntryType,
    WorkContract,
)


@pytest.fixture
def engine() -> DurableRemoteDispatchEngine:
    journal = DurableDispatchJournal()
    return DurableRemoteDispatchEngine(journal=journal)


@pytest.fixture
def sample_contract() -> WorkContract:
    return WorkContract(
        dispatch_id="dsp_test_001",
        task_name="remote_code_execution",
        target_peer_id="sandbox_node_alpha",
        coordinator_principal_id="coord_primary",
        max_budget_tokens=25000,
        expires_at=time.time() + 300.0,
        required_policies=["sandbox_isolation", "network_whitelist"],
    )


def test_prepare_dispatch_and_auth_check(
    engine: DurableRemoteDispatchEngine,
    sample_contract: WorkContract,
) -> None:
    # 1. Successful dispatch with valid coordinator token
    receipt = engine.prepare_dispatch(
        sample_contract,
        principal_token="valid_coordinator_token_123",
    )
    assert receipt.dispatch_id == "dsp_test_001"
    assert receipt.acknowledged_seq == 1
    assert receipt.prestart_verified is False
    assert receipt.peer_status == "accepted"

    journal = engine.journal.get_journal("dsp_test_001")
    assert len(journal) == 1
    assert journal[0].seq == 1
    assert journal[0].entry_type == JournalEntryType.DISPATCH_INIT

    # 2. Unauthorized coordinator principal
    with pytest.raises(PermissionError, match="Unauthorized coordinator principal"):
        engine.prepare_dispatch(
            sample_contract,
            principal_token="invalid_token",
        )


def test_pre_start_policy_revalidation_fail_closed(
    engine: DurableRemoteDispatchEngine,
    sample_contract: WorkContract,
) -> None:
    engine.prepare_dispatch(sample_contract)

    # 1. Missing policy -> Fail closed
    res_fail = engine.revalidate_pre_start_policy(
        "dsp_test_001",
        active_policies={"sandbox_isolation": True, "network_whitelist": False},
    )
    assert res_fail is False

    last_entry = engine.journal.get_latest_entry("dsp_test_001")
    assert last_entry is not None
    assert last_entry.entry_type == JournalEntryType.PRESTART_POLICY_FAIL

    # 2. Complete policies -> Pass
    res_pass = engine.revalidate_pre_start_policy(
        "dsp_test_001",
        active_policies={"sandbox_isolation": True, "network_whitelist": True},
    )
    assert res_pass is True

    last_entry_pass = engine.journal.get_latest_entry("dsp_test_001")
    assert last_entry_pass is not None
    assert last_entry_pass.entry_type == JournalEntryType.PRESTART_POLICY_PASS

    # 3. Expired contract -> Fail closed
    expired_contract = WorkContract(
        dispatch_id="dsp_expired",
        task_name="expired_task",
        target_peer_id="sandbox_node_beta",
        expires_at=time.time() - 10.0,
    )
    engine.prepare_dispatch(expired_contract)
    res_expired = engine.revalidate_pre_start_policy(
        "dsp_expired",
        active_policies={"sandbox_isolation": True, "network_whitelist": True, "credential_validity": True},
    )
    assert res_expired is False


def test_bounded_evidence_admission(
    engine: DurableRemoteDispatchEngine,
    sample_contract: WorkContract,
) -> None:
    engine.prepare_dispatch(sample_contract)

    # 1. Admissible evidence within bounds (1024 bytes)
    valid_evidence = EvidenceItem(
        evidence_id="evi_001",
        evidence_type="test_output",
        size_bytes=1024,
        content_digest="sha256_mock_digest_1",
        description="Linter passed with 0 errors",
    )
    admitted = engine.admit_evidence("dsp_test_001", valid_evidence)
    assert admitted is True
    assert valid_evidence.admitted is True

    evidence_items = engine.get_admitted_evidence("dsp_test_001")
    assert len(evidence_items) == 1

    # 2. Oversized evidence item exceeding 64KB -> Rejected
    oversized_evidence = EvidenceItem(
        evidence_id="evi_huge",
        evidence_type="memory_dump",
        size_bytes=MAX_SINGLE_EVIDENCE_BYTES + 512,
        content_digest="sha256_mock_huge",
    )
    admitted_huge = engine.admit_evidence("dsp_test_001", oversized_evidence)
    assert admitted_huge is False
    assert oversized_evidence.admitted is False

    last_entry = engine.journal.get_latest_entry("dsp_test_001")
    assert last_entry is not None
    assert last_entry.entry_type == JournalEntryType.EVIDENCE_REJECTED


def test_idempotent_crash_recovery_planning(
    engine: DurableRemoteDispatchEngine,
    sample_contract: WorkContract,
) -> None:
    engine.prepare_dispatch(sample_contract)
    engine.revalidate_pre_start_policy(
        "dsp_test_001",
        active_policies={"sandbox_isolation": True, "network_whitelist": True},
    )

    # 1. Recovery plan during execution -> Idempotent continue
    plan = engine.compute_recovery_plan("dsp_test_001")
    assert plan.can_resume is True
    assert plan.resume_action == "idempotent_continue_execution"

    last_entry = engine.journal.get_latest_entry("dsp_test_001")
    assert last_entry is not None
    assert last_entry.entry_type == JournalEntryType.RECOVERY_RESUMED

    # 2. Recovery plan after resolution -> Noop
    engine.resolve_dispatch("dsp_test_001", outcome_summary="Task successfully finished")
    plan_after = engine.compute_recovery_plan("dsp_test_001")
    assert plan_after.can_resume is False
    assert plan_after.resume_action == "noop_already_resolved"
