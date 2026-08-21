"""Unit tests for DeliverableConfidenceTier SSOT and resolve_deliverable_tier."""

import pytest
from myrm_agent_harness.agent.middlewares.completion.deliverable_confidence_tier import (
    DeliverableConfidenceTier,
    DeliverableTierEvidence,
    DeliverableTierMetadata,
    resolve_deliverable_tier,
)
from myrm_agent_harness.agent.security.guards.loop_guard import (
    CallRecord,
    SuccessLevel,
    VerificationCategory,
)
from myrm_agent_harness.agent.goals.verification.base import (
    AggregatedVerificationResult,
    VerificationResult,
)


def test_resolve_deliverable_tier_plan_when_empty():
    meta = resolve_deliverable_tier([])
    assert meta.tier == DeliverableConfidenceTier.PLAN
    assert meta.evidence.verification_count == 0
    assert len(meta.evidence.files_written) == 0
    assert meta.evidence.sources_count == 0


def test_resolve_deliverable_tier_verified_via_tool_record():
    records = [
        CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="hash1",
            args={"command": "pytest tests/"},
            verification_type=VerificationCategory.TEST,
            success_level=SuccessLevel.FULL_SUCCESS,
        )
    ]
    meta = resolve_deliverable_tier(records)
    assert meta.tier == DeliverableConfidenceTier.VERIFIED
    assert meta.evidence.verification_count == 1
    assert "test" in meta.evidence.verification_categories


def test_resolve_deliverable_tier_verified_via_gatekeeper():
    records = []
    gk_res = AggregatedVerificationResult(
        passed=True,
        per_criterion=[VerificationResult(passed=True, criterion_label="unit_tests")],
    )
    meta = resolve_deliverable_tier(records, gatekeeper_result=gk_res)
    assert meta.tier == DeliverableConfidenceTier.VERIFIED
    assert meta.evidence.gatekeeper_passed is True


def test_resolve_deliverable_tier_verified_via_cron():
    records = []
    meta = resolve_deliverable_tier(records, cron_verified=True)
    assert meta.tier == DeliverableConfidenceTier.VERIFIED


def test_resolve_deliverable_tier_artifact():
    records = [
        CallRecord(
            tool_name="file_write_tool",
            args_hash="hash2",
            args={"path": "workspace/output.pdf"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
    ]
    meta = resolve_deliverable_tier(records)
    assert meta.tier == DeliverableConfidenceTier.ARTIFACT
    assert "workspace/output.pdf" in meta.evidence.files_written


def test_resolve_deliverable_tier_research():
    records = [
        CallRecord(
            tool_name="web_search_tool",
            args_hash="hash3",
            args={"query": "agent frameworks 2026"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
    ]
    meta = resolve_deliverable_tier(records)
    assert meta.tier == DeliverableConfidenceTier.RESEARCH
    assert meta.evidence.sources_count == 1


def test_resolve_deliverable_tier_precedence_verified_over_artifact():
    records = [
        CallRecord(
            tool_name="file_edit_tool",
            args_hash="hash4",
            args={"path": "src/main.py"},
            success_level=SuccessLevel.FULL_SUCCESS,
        ),
        CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="hash5",
            args={"command": "pytest"},
            verification_type=VerificationCategory.TEST,
            success_level=SuccessLevel.FULL_SUCCESS,
        ),
    ]
    meta = resolve_deliverable_tier(records)
    assert meta.tier == DeliverableConfidenceTier.VERIFIED
    assert "src/main.py" in meta.evidence.files_written
    assert meta.evidence.verification_count == 1
    assert meta.to_dict()["tier"] == "VERIFIED"
