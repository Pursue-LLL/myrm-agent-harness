"""Unit tests for Automated Memory Diagnostic and Root Cause Inspector."""

import pytest

from myrm_agent_harness.toolkits.memory.diagnostic import (
    AutomatedMemoryDiagnosticInspector,
    DiagnosticStepKind,
    MemoryDiagnosticProbeContext,
    MemoryRootCauseKind,
)


@pytest.fixture
def inspector() -> AutomatedMemoryDiagnosticInspector:
    """Fixture providing a fresh memory diagnostic inspector."""
    return AutomatedMemoryDiagnosticInspector()


@pytest.fixture
def sample_context() -> MemoryDiagnosticProbeContext:
    """Fixture providing standard probe context."""
    return MemoryDiagnosticProbeContext(
        session_id="sess-diag-101",
        query_target_entity="postgresql_port_config",
        tenant_id="tenant-acme",
        user_id="user-alice",
        project_id="proj-db-infra",
        prompt_token_budget=1500,
    )


def test_healthy_memory_pipeline(
    inspector: AutomatedMemoryDiagnosticInspector,
    sample_context: MemoryDiagnosticProbeContext,
) -> None:
    """Test fully healthy pipeline execution where memory is retrieved and cited."""
    report = inspector.inspect(
        context=sample_context,
        session_exists=True,
        is_session_active=True,
        found_in_store=True,
        found_in_pending=False,
        is_superseded=False,
        is_expired=False,
        scope_matched=True,
        retrieved_rank=1,
        token_budget_exceeded=False,
        model_cited=True,
    )
    assert report.root_cause == MemoryRootCauseKind.HEALTHY
    assert report.overall_healthy is True
    assert len(report.step_results) == 5
    assert all(r.passed for r in report.step_results)
    assert "flawlessly" in report.remediation_advice


def test_step1_session_lost_diagnosis(
    inspector: AutomatedMemoryDiagnosticInspector,
    sample_context: MemoryDiagnosticProbeContext,
) -> None:
    """Test Step 1 failure when session state is lost or aborted."""
    report = inspector.inspect(
        context=sample_context,
        session_exists=False,
        is_session_active=False,
    )
    assert report.root_cause == MemoryRootCauseKind.SESSION_LOST
    assert report.overall_healthy is False
    assert len(report.step_results) == 1
    assert report.step_results[0].step_kind == DiagnosticStepKind.STEP1_SESSION_STATE
    assert report.step_results[0].passed is False
    assert "Restore" in report.remediation_advice or "Re-initialize" in report.remediation_advice


def test_step2_extraction_missed_diagnosis(
    inspector: AutomatedMemoryDiagnosticInspector,
    sample_context: MemoryDiagnosticProbeContext,
) -> None:
    """Test Step 2 failure when fact was never extracted into memory."""
    report = inspector.inspect(
        context=sample_context,
        session_exists=True,
        is_session_active=True,
        found_in_store=False,
        found_in_pending=False,
    )
    assert report.root_cause == MemoryRootCauseKind.EXTRACTION_MISSED
    assert report.overall_healthy is False
    assert len(report.step_results) == 2
    assert report.step_results[1].step_kind == DiagnosticStepKind.STEP2_EXTRACTION_CHECK
    assert report.step_results[1].passed is False
    assert "missed by extraction pipeline" in report.remediation_advice


def test_step3_fact_expired_or_superseded_diagnosis(
    inspector: AutomatedMemoryDiagnosticInspector,
    sample_context: MemoryDiagnosticProbeContext,
) -> None:
    """Test Step 3 failure when fact has been superseded or expired via TTL."""
    # Case: superseded
    report_sup = inspector.inspect(
        context=sample_context,
        session_exists=True,
        is_session_active=True,
        found_in_store=True,
        is_superseded=True,
        is_expired=False,
    )
    assert report_sup.root_cause == MemoryRootCauseKind.FACT_EXPIRED_OR_SUPERSEDED
    assert report_sup.overall_healthy is False
    assert report_sup.step_results[2].step_kind == DiagnosticStepKind.STEP3_EXPIRATION_AUDIT
    assert report_sup.step_results[2].passed is False

    # Case: expired by TTL
    report_exp = inspector.inspect(
        context=sample_context,
        session_exists=True,
        is_session_active=True,
        found_in_store=True,
        is_superseded=False,
        is_expired=True,
    )
    assert report_exp.root_cause == MemoryRootCauseKind.FACT_EXPIRED_OR_SUPERSEDED
    assert report_exp.overall_healthy is False


def test_step4_scope_mismatch_isolated_diagnosis(
    inspector: AutomatedMemoryDiagnosticInspector,
    sample_context: MemoryDiagnosticProbeContext,
) -> None:
    """Test Step 4 failure when query scope diverges from stored memory boundary."""
    report = inspector.inspect(
        context=sample_context,
        session_exists=True,
        is_session_active=True,
        found_in_store=True,
        is_superseded=False,
        is_expired=False,
        scope_matched=False,
        scope_details="Stored in project 'proj-secret', queried with 'proj-db-infra'.",
    )
    assert report.root_cause == MemoryRootCauseKind.SCOPE_MISMATCH_ISOLATED
    assert report.overall_healthy is False
    assert len(report.step_results) == 4
    assert report.step_results[3].step_kind == DiagnosticStepKind.STEP4_SCOPE_MATCHING
    assert report.step_results[3].passed is False
    assert "different tenant/project scope" in report.remediation_advice


def test_step5_budget_truncated_or_rank_dropped_diagnosis(
    inspector: AutomatedMemoryDiagnosticInspector,
    sample_context: MemoryDiagnosticProbeContext,
) -> None:
    """Test Step 5 failure when token budget limits or rank drop pruned the memory."""
    # Case: budget exceeded
    report_budget = inspector.inspect(
        context=sample_context,
        session_exists=True,
        is_session_active=True,
        found_in_store=True,
        is_superseded=False,
        is_expired=False,
        scope_matched=True,
        retrieved_rank=2,
        token_budget_exceeded=True,
    )
    assert report_budget.root_cause == MemoryRootCauseKind.BUDGET_TRUNCATED_OR_RANK_DROPPED
    assert report_budget.overall_healthy is False
    assert report_budget.step_results[4].step_kind == DiagnosticStepKind.STEP5_BUDGET_TRUNCATION
    assert report_budget.step_results[4].passed is False

    # Case: not in recall rank (rank is None)
    report_rank = inspector.inspect(
        context=sample_context,
        session_exists=True,
        is_session_active=True,
        found_in_store=True,
        is_superseded=False,
        is_expired=False,
        scope_matched=True,
        retrieved_rank=None,
        token_budget_exceeded=False,
    )
    assert report_rank.root_cause == MemoryRootCauseKind.BUDGET_TRUNCATED_OR_RANK_DROPPED
    assert report_rank.overall_healthy is False


def test_model_attention_ignored_diagnosis(
    inspector: AutomatedMemoryDiagnosticInspector,
    sample_context: MemoryDiagnosticProbeContext,
) -> None:
    """Test when fact was injected, but the LLM overlooked it during response synthesis."""
    report = inspector.inspect(
        context=sample_context,
        session_exists=True,
        is_session_active=True,
        found_in_store=True,
        is_superseded=False,
        is_expired=False,
        scope_matched=True,
        retrieved_rank=1,
        token_budget_exceeded=False,
        model_cited=False,  # Not cited!
    )
    assert report.root_cause == MemoryRootCauseKind.MODEL_ATTENTION_IGNORED
    assert report.overall_healthy is False
    assert all(r.passed for r in report.step_results)
    assert "LLM ignored or overlooked" in report.remediation_advice


def test_inspector_history_and_filtering(
    inspector: AutomatedMemoryDiagnosticInspector,
    sample_context: MemoryDiagnosticProbeContext,
) -> None:
    """Test inspection history accumulation and filtering by session_id."""
    inspector.inspect(sample_context, session_exists=True, model_cited=True)
    inspector.inspect(
        MemoryDiagnosticProbeContext(
            session_id="other-sess",
            query_target_entity="other_fact",
        ),
        session_exists=False,
    )
    assert inspector.total_inspections_conducted == 2

    # Filter by session
    sess_reports = inspector.list_reports(sample_context.session_id)
    assert len(sess_reports) == 1
    assert sess_reports[0].session_id == sample_context.session_id

    # All reports
    assert len(inspector.list_reports()) == 2
