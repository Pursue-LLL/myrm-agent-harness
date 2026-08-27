"""Tests for batch risk classification and dual insurance policies."""

from myrm_agent_harness.agent.security.batch_risk import (
    BatchApprovalItem,
    BatchItemRiskLevel,
    BatchRiskItemDetail,
    BatchRiskReport,
    classify_batch_approval_risk,
)


def test_classify_batch_approval_risk_all_safe():
    items = [
        BatchApprovalItem(
            item_id="appr-1",
            action_type="file_read",
            tool_name="read_file",
            severity="info",
        ),
        BatchApprovalItem(
            item_id="appr-2",
            action_type="web_search",
            tool_name="google_search",
            severity="low",
        ),
    ]

    report = classify_batch_approval_risk(items)
    assert not report.has_high_risk
    assert report.total_count == 2
    assert report.high_risk_count == 0
    assert report.safe_count == 2
    assert report.safe_item_ids == ("appr-1", "appr-2")
    assert len(report.high_risk_items) == 0


def test_classify_batch_approval_risk_mixed_smart_denied():
    items = [
        BatchApprovalItem(
            item_id="appr-safe",
            action_type="file_read",
            tool_name="read_file",
        ),
        BatchApprovalItem(
            item_id="appr-denied",
            action_type="shell_exec",
            tool_name="exec_command",
            is_smart_denied=True,
            reason="Dangerous command detected",
        ),
    ]

    report = classify_batch_approval_risk(items)
    assert report.has_high_risk
    assert report.total_count == 2
    assert report.high_risk_count == 1
    assert report.safe_count == 1
    assert report.safe_item_ids == ("appr-safe",)
    assert len(report.high_risk_items) == 1
    assert report.high_risk_items[0].item_id == "appr-denied"
    assert report.high_risk_items[0].risk_level == BatchItemRiskLevel.HIGH
    assert report.high_risk_items[0].risk_reason == "Dangerous command detected"


def test_classify_batch_approval_risk_payload_review_configs():
    items = [
        BatchApprovalItem(
            item_id="appr-cfg",
            action_type="subagent_approval",
            tool_name="subagent",
            payload={"reviewConfigs": [{"smartDenied": True}]},
        ),
        BatchApprovalItem(
            item_id="appr-destructive-act",
            action_type="delete_file",
            tool_name="file_deleter",
        ),
    ]

    report = classify_batch_approval_risk(items)
    assert report.has_high_risk
    assert report.total_count == 2
    assert report.high_risk_count == 2
    assert report.safe_count == 0
