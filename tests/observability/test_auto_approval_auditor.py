"""Tests for AutoApprovalAuditor and Security Audit Module."""

from myrm_agent_harness.observability.security_audit import (
    ApprovalTriggerCategory,
    ApprovalTriggerEvent,
    AutoApprovalAuditor,
    QuotaDimensionBreakdown,
)


def test_classify_target() -> None:
    assert AutoApprovalAuditor.classify_target("shell_exec", "ls -la") == ApprovalTriggerCategory.COMMAND_EXECUTION
    assert AutoApprovalAuditor.classify_target("bash", "git status") == ApprovalTriggerCategory.COMMAND_EXECUTION
    assert AutoApprovalAuditor.classify_target("web_fetch", "https://api.github.com") == ApprovalTriggerCategory.NETWORK_DOMAIN
    assert AutoApprovalAuditor.classify_target("mcp_invoke", "stripe.create_charge") == ApprovalTriggerCategory.TOOL_APPROVAL
    assert AutoApprovalAuditor.classify_target("file_write", "/etc/hosts") == ApprovalTriggerCategory.FILE_BOUNDARY_CROSS


def test_empty_events_audit() -> None:
    primary = QuotaDimensionBreakdown(role="primary", prompt_tokens=100, completion_tokens=50, cost_usd=0.002)
    auto_rev = QuotaDimensionBreakdown(role="auto_review", prompt_tokens=20, completion_tokens=10, cost_usd=0.0005)

    report = AutoApprovalAuditor.audit_session(
        session_id="sess_123",
        events=[],
        primary_quota=primary,
        auto_review_quota=auto_rev,
    )

    assert report.session_id == "sess_123"
    assert report.total_triggers == 0
    assert report.auto_approval_ratio == 0.0
    assert len(report.top_offenders) == 0
    assert report.primary_model_quota.total_tokens == 150
    assert report.auto_review_quota.total_tokens == 30


def test_full_session_audit_and_allowlist_recommendation() -> None:
    events = [
        ApprovalTriggerEvent(
            session_id="sess_abc",
            category=ApprovalTriggerCategory.FILE_BOUNDARY_CROSS,
            target="/workspace/project/temp.log",
            tool_name="write_file",
            auto_approved=True,
        ),
        ApprovalTriggerEvent(
            session_id="sess_abc",
            category=ApprovalTriggerCategory.FILE_BOUNDARY_CROSS,
            target="/workspace/project/temp2.log",
            tool_name="write_file",
            auto_approved=True,
        ),
        ApprovalTriggerEvent(
            session_id="sess_abc",
            category=ApprovalTriggerCategory.FILE_BOUNDARY_CROSS,
            target="/etc/passwd",
            tool_name="read_file",
            auto_approved=False,
        ),
        ApprovalTriggerEvent(
            session_id="sess_abc",
            category=ApprovalTriggerCategory.COMMAND_EXECUTION,
            target="sudo rm -rf /var/log",
            tool_name="bash",
            auto_approved=False,
        ),
        ApprovalTriggerEvent(
            session_id="sess_abc",
            category=ApprovalTriggerCategory.COMMAND_EXECUTION,
            target="npm test",
            tool_name="bash",
            auto_approved=True,
        ),
    ]

    primary = QuotaDimensionBreakdown(role="primary", call_rounds=5, prompt_tokens=1000, completion_tokens=200, cost_usd=0.02)
    auto_rev = QuotaDimensionBreakdown(role="auto_review", call_rounds=5, prompt_tokens=500, completion_tokens=50, cost_usd=0.005)

    report = AutoApprovalAuditor.audit_session(
        session_id="sess_abc",
        events=events,
        primary_quota=primary,
        auto_review_quota=auto_rev,
    )

    assert report.total_triggers == 5
    assert report.auto_approval_ratio == 0.6  # 3 out of 5 auto-approved
    assert report.category_counts[ApprovalTriggerCategory.FILE_BOUNDARY_CROSS] == 3
    assert report.category_counts[ApprovalTriggerCategory.COMMAND_EXECUTION] == 2

    # Verify top offenders safety checking
    top_targets = {item.target: item for item in report.top_offenders}

    # /etc/passwd or root path should be flagged as unsafe
    assert top_targets["sudo rm -rf /var/log"].is_safe_to_allowlist is False
    assert top_targets["sudo rm -rf /var/log"].risk_rationale is not None

    # npm test recommendation
    assert top_targets["npm test"].is_safe_to_allowlist is True
    assert top_targets["npm test"].recommended_pattern == "npm *"

    # /workspace/project/temp.log recommendation
    assert top_targets["/workspace/project/temp.log"].is_safe_to_allowlist is True
    assert top_targets["/workspace/project/temp.log"].recommended_pattern == "/workspace/project/*"
