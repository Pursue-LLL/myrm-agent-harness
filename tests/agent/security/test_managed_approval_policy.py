"""Tests for Managed Approval Policy model and gates."""

from __future__ import annotations

from myrm_agent_harness.agent.security.managed_approval_policy import (
    ManagedApprovalPolicy,
    load_managed_approval_policy_from_env,
)
from myrm_agent_harness.agent.security.managed_policy_gates import (
    effective_auto_mode_enabled,
    honor_allowlist,
    map_suppresses_yolo,
    yolo_allowed,
    yolo_allowed_for_model,
)
from myrm_agent_harness.agent.security.types import SecurityConfig


def test_empty_policy_is_noop() -> None:
    policy = ManagedApprovalPolicy.empty()
    assert honor_allowlist(policy, "claude-opus-4") is True
    assert yolo_allowed(policy) is True
    config = SecurityConfig(auto_mode_enabled=False)
    assert effective_auto_mode_enabled(config, policy, "claude-opus-4") is False


def test_ignore_allowlist_model_glob() -> None:
    policy = ManagedApprovalPolicy.from_mapping(
        {"ignoreAllowlistForModels": ["claude-opus*"]},
    )
    assert policy.should_ignore_allowlist("claude-opus-4-20250514") is True
    assert honor_allowlist(policy, "claude-opus-4-20250514") is False
    assert honor_allowlist(policy, "gpt-4o") is True


def test_force_auto_review_overrides_user_off() -> None:
    policy = ManagedApprovalPolicy.from_mapping(
        {"forceAutoReviewForModels": ["claude-opus*"]},
    )
    config = SecurityConfig(auto_mode_enabled=False)
    assert effective_auto_mode_enabled(config, policy, "claude-opus-4") is True


def test_disable_yolo() -> None:
    policy = ManagedApprovalPolicy.from_mapping({"disableYolo": True})
    assert yolo_allowed(policy) is False


def test_yolo_allowed_for_model_force_auto_review() -> None:
    policy = ManagedApprovalPolicy.from_mapping(
        {"forceAutoReviewForModels": ["claude-opus*"]},
    )
    assert yolo_allowed_for_model(policy, "claude-opus-4") is False
    assert yolo_allowed_for_model(policy, "gpt-4o") is True


def test_yolo_allowed_for_model_ignore_allowlist() -> None:
    policy = ManagedApprovalPolicy.from_mapping(
        {"ignoreAllowlistForModels": ["gpt-*"]},
    )
    assert map_suppresses_yolo(policy, "gpt-4o") is True
    assert yolo_allowed_for_model(policy, "gpt-4o") is False


def test_yolo_allowed_for_model_respects_global_disable() -> None:
    policy = ManagedApprovalPolicy.from_mapping({"disableYolo": True})
    assert yolo_allowed_for_model(policy, "gpt-4o") is False


def test_load_from_env_json() -> None:
    env = {
        "MYRM_MANAGED_APPROVAL_POLICY_JSON": (
            '{"ignoreAllowlistForModels":["gpt-*"],"disableYolo":true}'
        ),
    }
    policy = load_managed_approval_policy_from_env(env=env)
    assert policy.should_ignore_allowlist("gpt-4o") is True
    assert policy.disable_yolo is True


def test_load_from_env_invalid_json() -> None:
    policy = load_managed_approval_policy_from_env(
        env={"MYRM_MANAGED_APPROVAL_POLICY_JSON": "not-json"},
    )
    assert policy == ManagedApprovalPolicy.empty()
