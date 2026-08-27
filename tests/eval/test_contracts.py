"""Tests for 5-Contract Delivery Lifecycle State Machine."""

import pytest
from myrm_agent_harness.eval import (
    ContractStatus,
    DeliveryContractPhase,
    FiveContractStateSnapshot,
    PhaseContractRecord,
    build_initial_five_contract_state,
    evaluate_five_contract_progress,
)


def test_build_initial_five_contract_state() -> None:
    snapshot = build_initial_five_contract_state("Drafting new feature")
    assert isinstance(snapshot, FiveContractStateSnapshot)
    assert len(snapshot.contracts) == 5
    assert snapshot.current_phase == DeliveryContractPhase.TASK_INTENT
    assert snapshot.contracts[DeliveryContractPhase.TASK_INTENT.value].status == ContractStatus.IN_PROGRESS
    assert snapshot.contracts[DeliveryContractPhase.SCENE_ENVIRONMENT.value].status == ContractStatus.PENDING
    assert snapshot.is_fully_satisfied is False
    assert snapshot.has_violations is False


def test_evaluate_five_contract_progress_in_progress_execution() -> None:
    snapshot = evaluate_five_contract_progress(
        has_user_intent=True,
        workspace_ready=True,
        tool_calls_count=4,
        has_artifacts_produced=False,
        test_verification_passed=None,
    )
    assert snapshot.contracts[DeliveryContractPhase.TASK_INTENT.value].status == ContractStatus.SATISFIED
    assert snapshot.contracts[DeliveryContractPhase.SCENE_ENVIRONMENT.value].status == ContractStatus.SATISFIED
    assert snapshot.contracts[DeliveryContractPhase.ACTION_EXECUTION.value].status == ContractStatus.IN_PROGRESS
    assert snapshot.contracts[DeliveryContractPhase.DELIVERY_ARTIFACT.value].status == ContractStatus.IN_PROGRESS
    assert snapshot.contracts[DeliveryContractPhase.ACCEPTANCE_VERIFICATION.value].status == ContractStatus.PENDING
    assert snapshot.current_phase == DeliveryContractPhase.ACTION_EXECUTION
    assert snapshot.is_fully_satisfied is False


def test_evaluate_five_contract_progress_fully_satisfied() -> None:
    snapshot = evaluate_five_contract_progress(
        has_user_intent=True,
        workspace_ready=True,
        tool_calls_count=5,
        has_artifacts_produced=True,
        test_verification_passed=True,
    )
    assert snapshot.is_fully_satisfied is True
    assert snapshot.has_violations is False
    assert snapshot.overall_progress_pct == 100
    for phase_key in DeliveryContractPhase:
        assert snapshot.contracts[phase_key.value].status == ContractStatus.SATISFIED


def test_evaluate_five_contract_progress_with_violation() -> None:
    snapshot = evaluate_five_contract_progress(
        has_user_intent=True,
        workspace_ready=False,
        tool_calls_count=0,
        has_artifacts_produced=False,
        test_verification_passed=None,
        execution_error="Disk quota exhausted",
    )
    assert snapshot.has_violations is True
    assert snapshot.contracts[DeliveryContractPhase.SCENE_ENVIRONMENT.value].status == ContractStatus.VIOLATED
    assert "Disk quota exhausted" in snapshot.contracts[DeliveryContractPhase.SCENE_ENVIRONMENT.value].summary
