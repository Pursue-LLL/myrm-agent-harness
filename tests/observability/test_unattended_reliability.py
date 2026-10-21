"""Unit tests for Unattended Reliability Triad Self-Proof in myrm_agent_harness.observability.unattended_reliability."""

from concurrent.futures import ThreadPoolExecutor

from myrm_agent_harness.observability.unattended_reliability import (
    FinalReportingStatus,
    ReliabilityTriadScore,
    ResumeStatus,
    RunReliabilityRecord,
    SideEffectStatus,
    UnattendedReliabilityEvaluator,
)


def test_initial_evaluator_state() -> None:
    """Verify that evaluator initializes with clean default scores."""
    evaluator = UnattendedReliabilityEvaluator()
    score: ReliabilityTriadScore = evaluator.get_triad_score()

    assert score.total_evaluated_runs == 0
    assert score.resume_rate_pct == 100.0
    assert score.zero_duplicate_side_effect_rate_pct == 100.0
    assert score.honest_blocker_rate_pct == 100.0
    assert score.composite_triad_score == 100.0
    assert score.hallucinated_success_count == 0
    assert score.duplicate_side_effect_count == 0
    assert score.failed_resume_count == 0
    assert len(score.recent_records) == 0


def test_record_run_and_triad_scoring() -> None:
    """Verify metric calculations across the three reliability pillars."""
    evaluator = UnattendedReliabilityEvaluator()

    # 1. Fully healthy run with successful resume
    rec1 = evaluator.record_run(
        task_name="Cron sync job",
        resume_status=ResumeStatus.RESUMED_SUCCESS,
        side_effect_status=SideEffectStatus.ZERO_DUPLICATE,
        reporting_status=FinalReportingStatus.GENUINE_SUCCESS,
        detail="Resumed cleanly after container recreate",
    )
    assert rec1.resume_status == ResumeStatus.RESUMED_SUCCESS
    assert rec1.side_effect_status == SideEffectStatus.ZERO_DUPLICATE

    # 2. Failed resume with duplicate side effect but honest blocker
    evaluator.record_run(
        task_name="Deployment pipeline",
        resume_status=ResumeStatus.RESUMED_FAILED,
        side_effect_status=SideEffectStatus.DUPLICATE_DETECTED,
        reporting_status=FinalReportingStatus.HONEST_BLOCKER,
        detail="Failed to resume git checkout, truthfully reported blocker",
    )

    score = evaluator.get_triad_score()
    assert score.total_evaluated_runs == 2
    assert score.resume_rate_pct == 50.0  # 1 success out of 2 applicable
    assert score.zero_duplicate_side_effect_rate_pct == 50.0  # 1 zero-dup out of 2 applicable
    assert score.honest_blocker_rate_pct == 100.0  # 1 honest out of 1 blocker applicable
    assert score.failed_resume_count == 1
    assert score.duplicate_side_effect_count == 1
    assert score.hallucinated_success_count == 0


def test_hallucinated_success_penalization() -> None:
    """Verify that hallucinated success severely degrades the honest blocker rate."""
    evaluator = UnattendedReliabilityEvaluator()

    # Honest blocker
    evaluator.record_run(
        task_name="SSH remote task",
        reporting_status=FinalReportingStatus.HONEST_BLOCKER,
    )

    # Hallucinated success (claiming success when task failed)
    evaluator.record_run(
        task_name="Database migration",
        reporting_status=FinalReportingStatus.HALLUCINATED_SUCCESS,
        detail="AI claimed migration completed but table was not created",
    )

    score = evaluator.get_triad_score()
    assert score.total_evaluated_runs == 2
    assert score.hallucinated_success_count == 1
    # 1 genuine blocker vs 1 hallucinated success -> 50% honesty
    assert score.honest_blocker_rate_pct == 50.0


def test_self_proof_benchmark_runner() -> None:
    """Verify built-in self-proof benchmark executes repeatable verification scenarios."""
    evaluator = UnattendedReliabilityEvaluator()
    evaluator.reset()

    benchmark_score = evaluator.run_self_proof_benchmark()
    assert benchmark_score.total_evaluated_runs == 3
    assert benchmark_score.resume_rate_pct == 100.0
    assert benchmark_score.zero_duplicate_side_effect_rate_pct == 100.0
    assert benchmark_score.honest_blocker_rate_pct == 100.0
    assert benchmark_score.composite_triad_score == 100.0
    assert benchmark_score.hallucinated_success_count == 0
    assert benchmark_score.duplicate_side_effect_count == 0
    assert benchmark_score.failed_resume_count == 0


def test_concurrent_run_recording_thread_safety() -> None:
    """Verify thread safety under concurrent run recording."""
    evaluator = UnattendedReliabilityEvaluator(max_history=100)

    def worker_task(i: int) -> None:
        resume = ResumeStatus.RESUMED_SUCCESS if i % 2 == 0 else ResumeStatus.RESUMED_FAILED
        side = SideEffectStatus.ZERO_DUPLICATE if i % 3 != 0 else SideEffectStatus.DUPLICATE_DETECTED
        reporting = FinalReportingStatus.HONEST_BLOCKER if i % 4 == 0 else FinalReportingStatus.GENUINE_SUCCESS
        evaluator.record_run(
            task_name=f"Worker task {i}",
            resume_status=resume,
            side_effect_status=side,
            reporting_status=reporting,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker_task, range(60)))

    score = evaluator.get_triad_score()
    assert score.total_evaluated_runs == 60
    assert len(score.recent_records) == 60
