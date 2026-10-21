"""[INPUT] Harness review_loop submodule exports.
[OUTPUT] Unit tests verifying Tri-Perspective Reviewers, parallel dispatch, bounded review loop, and self-healing convergence.
[POS] Unit tests for Multi-Perspective Parallel Subagent Review & Bounded Review Loop (Item 32).
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.review_loop import (
    BoundedReviewLoopExecutor,
    FindingSeverity,
    MultiPerspectiveReviewPipeline,
    PerspectiveReviewReport,
    ReviewFinding,
    ReviewLoopStatus,
    ReviewPerspective,
    format_review_prompt,
    get_perspective_system_prompt,
)


def test_perspective_prompts_and_formatting() -> None:
    # 1. Specialized perspective system prompts
    correctness_prompt = get_perspective_system_prompt(ReviewPerspective.CORRECTNESS)
    assert "Correctness & Robustness" in correctness_prompt
    assert "NoneType" in correctness_prompt

    test_prompt = get_perspective_system_prompt(ReviewPerspective.TEST_COVERAGE)
    assert "Test Completeness" in test_prompt
    assert "Assertion Rigor" in test_prompt

    simplicity_prompt = get_perspective_system_prompt(ReviewPerspective.SIMPLICITY)
    assert "Simplicity & Anti-Over-Engineering" in simplicity_prompt
    assert "Single Responsibility" in simplicity_prompt

    # 2. Formatted review user prompt
    prompt = format_review_prompt(diff="def foo(): return 42", context="Refactor parser")
    assert "def foo(): return 42" in prompt
    assert "Refactor parser" in prompt


def test_parallel_review_pipeline_clean_diff() -> None:
    clean_diff = """
    def add(a: int, b: int) -> int:
        return a + b

    def test_add_success():
        assert add(1, 2) == 3
    """
    pipeline = MultiPerspectiveReviewPipeline()
    reports = pipeline.run_parallel_review(clean_diff)

    assert len(reports) == 3
    assert ReviewPerspective.CORRECTNESS in reports
    assert ReviewPerspective.TEST_COVERAGE in reports
    assert ReviewPerspective.SIMPLICITY in reports

    all_findings = pipeline.aggregate_findings(reports)
    has_blocking = pipeline.has_blocking_issues(all_findings)

    assert has_blocking is False
    assert reports[ReviewPerspective.CORRECTNESS].approved is True
    assert reports[ReviewPerspective.TEST_COVERAGE].approved is True
    assert reports[ReviewPerspective.SIMPLICITY].approved is True


def test_parallel_review_pipeline_detects_blocking_issues() -> None:
    buggy_diff = """
    def unfinished_worker():
        pass
    """
    pipeline = MultiPerspectiveReviewPipeline()
    reports = pipeline.run_parallel_review(buggy_diff)

    all_findings = pipeline.aggregate_findings(reports)
    assert len(all_findings) > 0
    assert pipeline.has_blocking_issues(all_findings) is True

    # Correctness detected pass stub
    corr_report = reports[ReviewPerspective.CORRECTNESS]
    assert corr_report.approved is False
    assert any("pass" in f.issue.lower() for f in corr_report.findings)

    # Test coverage detected missing tests
    test_report = reports[ReviewPerspective.TEST_COVERAGE]
    assert test_report.approved is False
    assert any("unit test" in f.issue.lower() for f in test_report.findings)


def test_bounded_review_loop_converges_cleanly_on_first_round() -> None:
    clean_diff = """
    def multiply(x: int, y: int) -> int:
        return x * y

    def test_multiply():
        assert multiply(2, 3) == 6
    """
    executor = BoundedReviewLoopExecutor(max_rounds=3)
    result = executor.run_loop(clean_diff)

    assert result.status == ReviewLoopStatus.CONVERGED
    assert result.is_clean is True
    assert result.total_rounds == 1
    assert result.rounds[0].converged is True
    assert result.rounds[0].has_blocking_issues is False


def test_bounded_review_loop_self_heals_and_converges() -> None:
    # Round 1 will fail due to pass stub and missing tests,
    # then default_simulated_fix_worker will remediate it,
    # and Round 2 will pass cleanly.
    initial_diff = """
    def compute_value():
        pass
    """
    executor = BoundedReviewLoopExecutor(max_rounds=3)
    result = executor.run_loop(initial_diff)

    assert result.status == ReviewLoopStatus.CONVERGED
    assert result.is_clean is True
    assert result.total_rounds == 2

    # Round 1 had issues and applied fixes
    round_1 = result.rounds[0]
    assert round_1.converged is False
    assert round_1.has_blocking_issues is True
    assert round_1.fix_description is not None
    assert "Replaced stub pass" in round_1.fix_description

    # Round 2 converged
    round_2 = result.rounds[1]
    assert round_2.converged is True
    assert round_2.has_blocking_issues is False


def test_bounded_review_loop_enforces_max_rounds_bound() -> None:
    # Stubborn reviewer that always finds a blocker
    def stubborn_reviewer(perspective: ReviewPerspective, diff: str, context: str | None) -> PerspectiveReviewReport:
        finding = ReviewFinding(
            perspective=perspective,
            severity=FindingSeverity.BLOCKER,
            file_path="security_gate.py",
            issue="Stubborn persistent blocker that cannot be resolved",
            suggestion="Manual human intervention required",
        )
        return PerspectiveReviewReport(
            perspective=perspective,
            reviewer_name="stubborn-reviewer",
            approved=False,
            findings=(finding,),
            summary="Stubborn reviewer rejected changes.",
        )

    pipeline = MultiPerspectiveReviewPipeline(custom_handler=stubborn_reviewer)
    executor = BoundedReviewLoopExecutor(pipeline=pipeline, max_rounds=3)

    result = executor.run_loop("some diff", loop_id="test_bounded_loop_01")

    # Strictly halted at 3 rounds; no infinite loop!
    assert result.status == ReviewLoopStatus.MAX_ROUNDS_REACHED
    assert result.is_clean is False
    assert result.total_rounds == 3
    assert result.max_rounds == 3
    assert len(result.rounds) == 3
    assert result.rounds[-1].has_blocking_issues is True
    assert "Reached maximum allowed review rounds" in (result.rounds[-1].fix_description or "")
