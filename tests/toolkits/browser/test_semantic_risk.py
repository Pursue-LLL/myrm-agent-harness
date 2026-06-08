"""Tests for semantic DOM risk classification module.

Validates that browser element interactions are correctly classified as
safe or high-risk based on the semantic content (role + name) of the
target element from the ARIA snapshot.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo
from myrm_agent_harness.toolkits.browser.tools._semantic_risk import (
    SemanticRiskLevel,
    classify_interaction_risk,
)


def _ref(role: str = "button", name: str = "Submit") -> RefInfo:
    return RefInfo(role=role, name=name, nth=None)


# ──────────────────────────────────────────────────────────────────
# Safe actions (non-mutating actions should never trigger)
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("action", ["hover", "focus", "scroll", "type", "fill", "press", "select"])
def test_non_mutating_actions_always_safe(action: str):
    ref = _ref("button", "Delete Repository")
    verdict = classify_interaction_risk(action, ref)
    assert verdict.level is SemanticRiskLevel.SAFE


# ──────────────────────────────────────────────────────────────────
# Safe click targets (benign element names)
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "Submit",
        "Search",
        "Next",
        "Continue",
        "Save",
        "Open",
        "Close",
        "Cancel",
        "Apply Filter",
        "Download PDF",
        "View Details",
    ],
)
def test_benign_click_targets_safe(name: str):
    verdict = classify_interaction_risk("click", _ref("button", name))
    assert verdict.level is SemanticRiskLevel.SAFE


# ──────────────────────────────────────────────────────────────────
# High-risk: destructive actions
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "Delete Repository",
        "Remove User",
        "Destroy Instance",
        "Terminate Session",
        "Purge Cache",
        "Drop Table",
        "Erase All Data",
        "Wipe Device",
        "Format Disk",
    ],
)
def test_destructive_click_high_risk(name: str):
    verdict = classify_interaction_risk("click", _ref("button", name))
    assert verdict.level is SemanticRiskLevel.HIGH
    assert "destructive" in verdict.reason.lower() or "Destructive" in verdict.reason


# ──────────────────────────────────────────────────────────────────
# High-risk: financial actions
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "Pay Now",
        "Purchase Plan",
        "Buy Credits",
        "Checkout",
        "Subscribe Monthly",
        "Place Order",
        "Confirm Payment",
    ],
)
def test_financial_click_high_risk(name: str):
    verdict = classify_interaction_risk("click", _ref("button", name))
    assert verdict.level is SemanticRiskLevel.HIGH
    assert "financial" in verdict.reason.lower() or "Financial" in verdict.reason


# ──────────────────────────────────────────────────────────────────
# High-risk: account modification
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "Deactivate Account",
        "Close Account",
        "Delete Account",
        "Revoke Access",
        "Unsubscribe",
    ],
)
def test_account_click_high_risk(name: str):
    verdict = classify_interaction_risk("click", _ref("button", name))
    assert verdict.level is SemanticRiskLevel.HIGH


# ──────────────────────────────────────────────────────────────────
# High-risk: admin / infra actions
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "Shutdown Server",
        "Reboot Machine",
        "Restart Service",
        "Deploy to Production",
        "Rollback Version",
        "Reset Settings",
        "Factory Reset",
    ],
)
def test_admin_click_high_risk(name: str):
    verdict = classify_interaction_risk("click", _ref("button", name))
    assert verdict.level is SemanticRiskLevel.HIGH


# ──────────────────────────────────────────────────────────────────
# High-risk: publishing / broadcast
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "Publish Article",
        "Send to All",
        "Broadcast Message",
        "Announce Update",
    ],
)
def test_publish_click_high_risk(name: str):
    verdict = classify_interaction_risk("click", _ref("button", name))
    assert verdict.level is SemanticRiskLevel.HIGH


# ──────────────────────────────────────────────────────────────────
# High-risk: Chinese language elements
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "删除仓库",
        "移除成员",
        "销毁实例",
        "清空数据",
        "终止进程",
        "付款",
        "支付订单",
        "购买套餐",
        "下单",
        "注销账号",
        "停用服务",
        "发布文章",
        "广播消息",
    ],
)
def test_chinese_elements_high_risk(name: str):
    verdict = classify_interaction_risk("click", _ref("button", name))
    assert verdict.level is SemanticRiskLevel.HIGH


# ──────────────────────────────────────────────────────────────────
# Double-click should also trigger
# ──────────────────────────────────────────────────────────────────


def test_dblclick_also_triggers():
    verdict = classify_interaction_risk("dblclick", _ref("button", "Delete All"))
    assert verdict.level is SemanticRiskLevel.HIGH


# ──────────────────────────────────────────────────────────────────
# Alert dialog role
# ──────────────────────────────────────────────────────────────────


def test_alertdialog_role_high_risk():
    verdict = classify_interaction_risk("click", _ref("alertdialog", "Confirm deletion?"))
    assert verdict.level is SemanticRiskLevel.HIGH
    assert "alert dialog" in verdict.reason.lower()


# ──────────────────────────────────────────────────────────────────
# Case insensitivity
# ──────────────────────────────────────────────────────────────────


def test_case_insensitive_matching():
    verdict = classify_interaction_risk("click", _ref("button", "DELETE EVERYTHING"))
    assert verdict.level is SemanticRiskLevel.HIGH


# ──────────────────────────────────────────────────────────────────
# Word boundary: "delete" inside other words should NOT trigger
# ──────────────────────────────────────────────────────────────────


def test_word_boundary_no_false_positive():
    verdict = classify_interaction_risk("click", _ref("button", "Undelete Item"))
    assert verdict.level is SemanticRiskLevel.SAFE


# ──────────────────────────────────────────────────────────────────
# Different roles (not just button)
# ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["link", "menuitem", "option", "treeitem"])
def test_various_roles_trigger(role: str):
    verdict = classify_interaction_risk("click", _ref(role, "Delete Record"))
    assert verdict.level is SemanticRiskLevel.HIGH


# ──────────────────────────────────────────────────────────────────
# Reason string format
# ──────────────────────────────────────────────────────────────────


def test_reason_contains_element_info():
    verdict = classify_interaction_risk("click", _ref("button", "Delete Repository"))
    assert verdict.level is SemanticRiskLevel.HIGH
    assert "button" in verdict.reason
    assert "Delete Repository" in verdict.reason


# ──────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────


def test_empty_name_safe():
    verdict = classify_interaction_risk("click", _ref("button", ""))
    assert verdict.level is SemanticRiskLevel.SAFE


def test_none_nth_handled():
    ref = RefInfo(role="button", name="Delete", nth=None)
    verdict = classify_interaction_risk("click", ref)
    assert verdict.level is SemanticRiskLevel.HIGH


def test_with_bbox_and_position():
    from myrm_agent_harness.toolkits.browser.snapshot.aria_types import BBox

    bbox = BBox(10, 20, 100, 50, 60, 45, 10, 20, 1920, 1080)
    ref = RefInfo(role="button", name="Terminate Instance", nth=0, bbox=bbox, position="at top-right")
    verdict = classify_interaction_risk("click", ref)
    assert verdict.level is SemanticRiskLevel.HIGH
