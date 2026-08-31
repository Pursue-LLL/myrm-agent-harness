"""Unit tests for Auto-Approval Trigger Diagnostics and Multi-Dimensional Quota Attribution Auditor."""

import pytest

from myrm_agent_harness.observability.approval_audit import (
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    AutoApprovalAuditReport,
    AutoApprovalAuditor,
    DualTrackQuotaBreakdown,
    TopOffenderItem,
)


def test_target_normalization_across_all_four_categories():
    """Test pure-rule normalization of URLs, paths, commands, and tool names."""
    auditor = AutoApprovalAuditor()

    # 1. FILE_BOUNDARY: extract parent folder wildcard
    assert auditor.normalize_target("/var/log/nginx/access.log", ApprovalTriggerCategory.FILE_BOUNDARY) == "/var/log/nginx/*"
    assert auditor.normalize_target("app.py", ApprovalTriggerCategory.FILE_BOUNDARY) == "./*"

    # 2. NETWORK_DOMAIN: extract domain/host
    assert auditor.normalize_target("https://api.github.com:443/repos/octocat", ApprovalTriggerCategory.NETWORK_DOMAIN) == "api.github.com"
    assert auditor.normalize_target("gitlab.com/api/v4", ApprovalTriggerCategory.NETWORK_DOMAIN) == "gitlab.com"

    # 3. COMMAND_EXECUTION: extract executable basename
    assert auditor.normalize_target("rm -rf /tmp/test_dir", ApprovalTriggerCategory.COMMAND_EXECUTION) == "rm"
    assert auditor.normalize_target("/usr/local/bin/curl -X POST https://example.com", ApprovalTriggerCategory.COMMAND_EXECUTION) == "curl"

    # 4. TOOL_ELEVATION: extract namespace prefix
    assert auditor.normalize_target("mcp__github__create_issue", ApprovalTriggerCategory.TOOL_ELEVATION) == "mcp__github"
    assert auditor.normalize_target("custom_tool", ApprovalTriggerCategory.TOOL_ELEVATION) == "custom_tool"


def test_suggest_allow_pattern():
    """Test minimal-privilege allowlist pattern generation."""
    auditor = AutoApprovalAuditor()

    assert auditor.suggest_allow_pattern("/workspace/data/*", ApprovalTriggerCategory.FILE_BOUNDARY) == "/workspace/data/*"
    assert auditor.suggest_allow_pattern("api.openai.com", ApprovalTriggerCategory.NETWORK_DOMAIN) == "*.api.openai.com"
    assert auditor.suggest_allow_pattern("git", ApprovalTriggerCategory.COMMAND_EXECUTION) == "git *"
    assert auditor.suggest_allow_pattern("mcp__filesystem", ApprovalTriggerCategory.TOOL_ELEVATION) == "mcp__filesystem::*"


def test_dual_track_quota_and_top_offenders_evaluation():
    """Test full event aggregation, dual-track quota separation, and bounded Top-Offenders."""
    auditor = AutoApprovalAuditor(
        max_tracked_offenders=5,
        price_per_million_prompt=2.0,
        price_per_million_completion=10.0,
        price_per_million_cached=0.5,
    )

    session_id = "sess_audit_test_001"
    events: list[ApprovalTriggerEvent] = []

    # 3x File Boundary events on /var/log/app.log
    for _ in range(3):
        events.append(
            auditor.record_trigger(
                session_id=session_id,
                raw_target="/var/log/app.log",
                category=ApprovalTriggerCategory.FILE_BOUNDARY,
                tool_name="read_file",
                prompt_tokens=1_000,
                completion_tokens=200,
                cached_prompt_tokens=800,
            )
        )

    # 2x Command Execution events on rm
    for _ in range(2):
        events.append(
            auditor.record_trigger(
                session_id=session_id,
                raw_target="rm -f /tmp/dummy.txt",
                category=ApprovalTriggerCategory.COMMAND_EXECUTION,
                tool_name="bash_exec",
                prompt_tokens=2_000,
                completion_tokens=100,
                cached_prompt_tokens=1_500,
            )
        )

    # 1x Network Domain event on api.anthropic.com
    events.append(
        auditor.record_trigger(
            session_id=session_id,
            raw_target="https://api.anthropic.com/v1/messages",
            category=ApprovalTriggerCategory.NETWORK_DOMAIN,
            tool_name="web_fetch",
            prompt_tokens=500,
            completion_tokens=50,
            cached_prompt_tokens=400,
        )
    )

    report: AutoApprovalAuditReport = auditor.evaluate_events(
        events,
        session_id=session_id,
        main_task_rounds=10,
        main_task_prompt_tokens=50_000,
        main_task_completion_tokens=5_000,
        main_task_cached_tokens=40_000,
        main_task_cost_usd=0.09,
    )

    # 1. Total triggers and category counts
    assert report.total_triggers == 6
    assert report.category_counts[ApprovalTriggerCategory.FILE_BOUNDARY] == 3
    assert report.category_counts[ApprovalTriggerCategory.COMMAND_EXECUTION] == 2
    assert report.category_counts[ApprovalTriggerCategory.NETWORK_DOMAIN] == 1
    assert report.category_counts[ApprovalTriggerCategory.TOOL_ELEVATION] == 0

    # 2. Dual-track quota decoupling
    dual = report.dual_track_breakdown
    assert dual.main_task_rounds == 10
    assert dual.audit_rounds == 6
    assert dual.total_rounds == 16
    assert dual.audit_cost_usd > 0.0
    assert dual.total_cost_usd > dual.main_task_cost_usd
    assert 0.0 < dual.audit_cost_ratio < 1.0
    assert 0.0 < dual.audit_token_ratio < 1.0

    # 3. Top-Offenders sorting
    assert len(report.top_offenders) == 3
    # Top 1 should be /var/log/* (3 hits)
    top1 = report.top_offenders[0]
    assert top1.normalized_target == "/var/log/*"
    assert top1.category == ApprovalTriggerCategory.FILE_BOUNDARY
    assert top1.hit_count == 3
    assert top1.suggested_allow_pattern == "/var/log/*"

    # Top 2 should be rm (2 hits)
    top2 = report.top_offenders[1]
    assert top2.normalized_target == "rm"
    assert top2.category == ApprovalTriggerCategory.COMMAND_EXECUTION
    assert top2.hit_count == 2
    assert top2.suggested_allow_pattern == "rm *"

    # Recommendations generated
    assert len(report.recommendations) >= 2
    assert any("Consider allowlisting" in rec for rec in report.recommendations)
