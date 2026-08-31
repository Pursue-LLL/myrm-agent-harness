"""Unit tests for Auto-Approval Trigger Diagnostics and Quota Attribution Auditor."""

import pytest

from myrm_agent_harness.observability.approval_audit import (
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    AutoApprovalAuditReport,
    AutoApprovalAuditor,
    DualTrackQuotaBreakdown,
    TopOffenderItem,
)


def test_categorization_and_normalization():
    """Test pure-rule classification and target normalization."""
    # 1. Network domain
    cat_net = AutoApprovalAuditor.categorize_target("web_fetch", "https://api.github.com/v1/repos/open-perplexity")
    assert cat_net == ApprovalTriggerCategory.NETWORK_DOMAIN
    norm_net = AutoApprovalAuditor.normalize_target(cat_net, "https://api.github.com/v1/repos/open-perplexity")
    assert norm_net == "api.github.com"
    pat_net = AutoApprovalAuditor.suggest_allow_pattern(cat_net, norm_net)
    assert pat_net == "*.github.com"

    # 2. File boundary
    cat_file = AutoApprovalAuditor.categorize_target("file_write", "/tmp/artifacts/report.pdf")
    assert cat_file == ApprovalTriggerCategory.FILE_BOUNDARY
    norm_file = AutoApprovalAuditor.normalize_target(cat_file, "/tmp/artifacts/report.pdf")
    assert norm_file == "/tmp/artifacts/*"
    pat_file = AutoApprovalAuditor.suggest_allow_pattern(cat_file, norm_file)
    assert pat_file == "/tmp/artifacts/*"

    # 3. Command execution
    cat_cmd = AutoApprovalAuditor.categorize_target("shell_exec", "pip install -r requirements.txt")
    assert cat_cmd == ApprovalTriggerCategory.COMMAND_EXECUTION
    norm_cmd = AutoApprovalAuditor.normalize_target(cat_cmd, "pip install -r requirements.txt")
    assert norm_cmd == "pip"
    pat_cmd = AutoApprovalAuditor.suggest_allow_pattern(cat_cmd, norm_cmd)
    assert pat_cmd == "pip *"

    # 4. Tool elevation
    cat_tool = AutoApprovalAuditor.categorize_target("mcp_invoke", "stripe_mcp:create_payment")
    assert cat_tool == ApprovalTriggerCategory.TOOL_ELEVATION
    norm_tool = AutoApprovalAuditor.normalize_target(cat_tool, "stripe_mcp:create_payment")
    assert norm_tool == "stripe_mcp"
    pat_tool = AutoApprovalAuditor.suggest_allow_pattern(cat_tool, norm_tool)
    assert pat_tool == "stripe_mcp:*"


def test_dual_track_breakdown_properties():
    """Test DualTrackQuotaBreakdown ratio and accumulation properties."""
    dual = DualTrackQuotaBreakdown(
        main_task_rounds=10,
        main_task_tokens=50_000,
        main_task_cost_usd=0.10,
        audit_rounds=5,
        audit_tokens=5_000,
        audit_cost_usd=0.02,
    )
    assert dual.total_rounds == 15
    assert dual.total_tokens == 55_000
    assert dual.total_cost_usd == 0.12
    # 0.02 / 0.12 = 0.1667 -> 16.67%
    assert round(dual.audit_cost_ratio, 2) == 0.17


def test_auto_approval_auditor_aggregation_and_report():
    """Test AutoApprovalAuditor end-to-end recording, Top-Offenders, and report generation."""
    auditor = AutoApprovalAuditor(max_tracked_offenders=10)

    # 1. Record main task usage
    auditor.record_main_task_usage(rounds=8, tokens=40_000, cost_usd=0.08)

    # 2. Record several trigger events
    # 3 events to api.github.com
    for _ in range(3):
        auditor.record_trigger_event(
            session_id="sess_test_1",
            tool_name="web_fetch",
            raw_target="https://api.github.com/v1/repos",
            prompt_tokens=500,
            completion_tokens=50,
            cost_usd=0.001,
        )

    # 1 event to shell rm
    auditor.record_trigger_event(
        session_id="sess_test_1",
        tool_name="shell_exec",
        raw_target="rm -rf /tmp/cache",
        prompt_tokens=400,
        completion_tokens=20,
        cost_usd=0.0008,
    )

    # 3. Generate report
    report = auditor.generate_report(session_id="sess_test_1", top_n=5)

    assert report.session_id == "sess_test_1"
    assert report.total_triggers == 4
    assert report.category_counts[ApprovalTriggerCategory.NETWORK_DOMAIN] == 3
    assert report.category_counts[ApprovalTriggerCategory.COMMAND_EXECUTION] == 1
    assert report.category_counts[ApprovalTriggerCategory.FILE_BOUNDARY] == 0

    # Dual track check
    assert report.dual_track_breakdown.main_task_rounds == 8
    assert report.dual_track_breakdown.audit_rounds == 4
    assert report.dual_track_breakdown.audit_tokens == (550 * 3) + 420

    # Top offenders check (api.github.com should be rank 1)
    assert len(report.top_offenders) == 2
    top1 = report.top_offenders[0]
    assert top1.normalized_target == "api.github.com"
    assert top1.hit_count == 3
    assert top1.suggested_allow_pattern == "*.github.com"

    # Recommendations check
    assert len(report.recommendations) >= 1
    assert "api.github.com" in report.recommendations[0]


def test_auditor_bounded_memory_limit():
    """Test that unique offender tracking is bounded by max_tracked_offenders."""
    auditor = AutoApprovalAuditor(max_tracked_offenders=3)

    for i in range(10):
        auditor.record_trigger_event(
            session_id="sess_bound",
            tool_name="web_fetch",
            raw_target=f"https://sub{i}.domain.com/path",
        )

    report = auditor.generate_report(session_id="sess_bound", top_n=10)
    # Total unique offenders should not exceed 3
    assert len(report.top_offenders) == 3
