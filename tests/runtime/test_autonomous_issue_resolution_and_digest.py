"""Unit tests for AutonomousIssueResolutionPipeline and EngineeringDigestEngine.

Tests benchmarked against Today Huajuan autonomous issue resolution & digest practices:
1. Issue scanner and triage: priority assessment, affected file extraction, proposal generation.
2. Isolated sandbox branch resolution, automated verification, and human-in-the-loop PR generation.
3. Test failure safety barrier: blocks PR generation when sandbox verification fails.
4. Morning Brief and Evening Brief compilation and markdown/JSON rendering.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.issue_resolution import (
    DigestKind,
    EngineeringDigestEngine,
    FixPlanProposal,
    IssuePriority,
    IssueResolutionStatus,
    IssueScannerAndPlanner,
    PullRequestPayload,
    RepositoryIssue,
    SandboxFixAndPrPipeline,
)


def test_issue_scanner_priority_and_planning() -> None:
    """Test priority derivation, affected file extraction, and proposal markdown rendering."""
    scanner = IssueScannerAndPlanner()

    critical_issue = RepositoryIssue(
        issue_id=60,
        repo="acme/wesight",
        title="Crash when parsing malformed video frame header",
        body="Fatal crash occurred in src/wesight/parser.py when reading invalid frame. Need tests in tests/test_parser.py.",
        labels=("security", "bug"),
        status=IssueResolutionStatus.OPEN,
    )

    priority = scanner.assess_priority(critical_issue)
    assert priority == IssuePriority.CRITICAL

    files = scanner.extract_affected_files(critical_issue.body)
    assert "src/wesight/parser.py" in files
    assert "tests/test_parser.py" in files

    proposal = scanner.generate_proposal(critical_issue, default_target_branch="main")
    assert proposal.issue_id == 60
    assert proposal.repo == "acme/wesight"
    assert proposal.target_branch == "main"
    assert proposal.estimated_risk == "High"  # Critical priority -> High risk
    assert proposal.automated_confidence >= 0.90
    assert "src/wesight/parser.py" in proposal.affected_files

    md = scanner.render_proposals_markdown([proposal])
    assert "### 🛠️ 待修 Issue 自动化分析与修复建议" in md
    assert "#60" in md
    assert "acme/wesight" in md


def test_sandbox_fix_and_pr_pipeline_success() -> None:
    """Test successful sandbox repair yielding audited PR while adhering to human-in-the-loop gate."""
    pipeline = SandboxFixAndPrPipeline(pr_id_sequence_start=101)

    issue = RepositoryIssue(
        issue_id=60,
        repo="acme/wesight",
        title="Crash when parsing malformed video frame header",
        body="Details in src/wesight/parser.py",
        status=IssueResolutionStatus.OPEN,
    )

    proposal = FixPlanProposal(
        proposal_id="prop_001",
        issue_id=60,
        repo="acme/wesight",
        target_branch="main",
        plan_summary="Add bounds checking in frame header parser",
        affected_files=("src/wesight/parser.py",),
        estimated_risk="Low",
        automated_confidence=0.95,
    )

    status, pr = pipeline.execute_sandbox_repair(issue, proposal, simulate_test_success=True)

    # Human-in-the-loop: status must be PR_PENDING_MERGE, never automatically merged
    assert status == IssueResolutionStatus.PR_PENDING_MERGE
    assert pr is not None
    assert pr.pr_id == 101
    assert pr.source_branch == "fix/issue-60"
    assert pr.target_branch == "main"
    assert pr.related_issue_id == 60
    assert pr.verification_passed is True
    assert "src/wesight/parser.py" in pr.diff_summary

    pr_card = pipeline.render_pr_markdown_card(pr)
    assert "### 🚀 Pull Request #101 已生成 (等待人工审核合并)" in pr_card
    assert "fix/issue-60" in pr_card
    assert "> [!NOTE]" in pr_card


def test_sandbox_fix_failure_barrier() -> None:
    """Test safety barrier blocking PR creation when sandbox tests fail."""
    pipeline = SandboxFixAndPrPipeline()

    issue = RepositoryIssue(
        issue_id=61,
        repo="acme/wesight",
        title="Unstable memory allocation",
        body="Memory leak in audio buffer",
        status=IssueResolutionStatus.OPEN,
    )

    proposal = FixPlanProposal(
        proposal_id="prop_002",
        issue_id=61,
        repo="acme/wesight",
        target_branch="main",
        plan_summary="Free buffer memory",
        affected_files=("src/wesight/audio.py",),
        estimated_risk="Medium",
        automated_confidence=0.85,
    )

    status, pr = pipeline.execute_sandbox_repair(issue, proposal, simulate_test_success=False)

    assert status == IssueResolutionStatus.FAILED
    assert pr is None


def test_engineering_digest_morning_and_evening() -> None:
    """Test compiling and rendering Morning Brief and Evening Brief."""
    engine = EngineeringDigestEngine()

    dummy_pr = PullRequestPayload(
        pr_id=101,
        repo="acme/wesight",
        source_branch="fix/issue-60",
        target_branch="main",
        title="fix(wesight): resolve #60 frame crash",
        diff_summary="1 file changed",
        related_issue_id=60,
        automated_review_notes="All tests passed",
        verification_passed=True,
    )

    resolved_iss = RepositoryIssue(
        issue_id=59,
        repo="acme/wesight",
        title="Typo in CLI help documentation",
        body="Fixed typo in docs",
        priority=IssuePriority.LOW,
        status=IssueResolutionStatus.MERGED,
    )

    # 1. Morning Brief
    morning = engine.generate_morning_brief(
        projects_monitored=["acme/wesight", "acme/dashboard"],
        pending_merge_prs=[dummy_pr],
        upcoming_tasks=["Review PR #60", "Run stress tests for decoder"],
    )
    assert morning.kind == DigestKind.MORNING_BRIEF
    assert len(morning.pending_merge_prs) == 1
    assert len(morning.upcoming_tasks) == 2

    m_card = engine.render_markdown_brief(morning)
    assert "### ☀️ 晨间工程简报 (Morning Brief)" in m_card
    assert "待人工审查合并的 Pull Requests" in m_card
    assert "#101" in m_card
    assert "今日重点排期计划" in m_card

    # 2. Evening Brief
    evening = engine.generate_evening_brief(
        projects_monitored=["acme/wesight"],
        resolved_issues=[resolved_iss],
        pending_merge_prs=[dummy_pr],
        open_risks=["Ffmpeg codec missing on ARM server"],
        tomorrow_tasks=["Deploy v1.2.0 patch"],
    )
    assert evening.kind == DigestKind.EVENING_BRIEF
    assert len(evening.resolved_issues) == 1
    assert len(evening.open_risks) == 1

    e_card = engine.render_markdown_brief(evening)
    assert "### 🌙 晚间工程复盘 (Evening Brief)" in e_card
    assert "已闭环解决的 Issues" in e_card
    assert "> [!WARNING]" in e_card
    assert "Ffmpeg codec missing on ARM server" in e_card

    # 3. JSON summary export
    json_data = engine.render_json_summary(evening)
    assert json_data["kind"] == "evening_brief"
    assert json_data["pending_prs_count"] == 1
    assert json_data["resolved_issues_count"] == 1
    assert len(json_data["open_risks"]) == 1  # type: ignore[arg-type]
