"""Unit tests for DeviceSecurityPolicy and evaluate_batch_risk.

Validates dual insurance, batch size thresholds, intra-tool compound command risks,
read-only fast-pass batches, and allowlist block escalation.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.device_policy import (
    DeviceSecurityPolicy,
    evaluate_batch_risk,
)


def test_device_security_policy_defaults():
    policy = DeviceSecurityPolicy.default()
    assert policy.max_batch_size == 15
    assert policy.enforce_dual_insurance is True
    assert policy.destructive_batch_size_threshold == 3
    assert "rm" in policy.high_risk_verbs
    assert "kill" in policy.high_risk_verbs
    assert ".env" in policy.restricted_paths


def test_single_read_only_tool_call_is_safe():
    tool_calls = [
        {"name": "file_read", "args": {"path": "/workspace/README.md"}},
    ]
    assessment = evaluate_batch_risk(tool_calls)
    assert assessment.is_batch is False
    assert assessment.batch_size == 1
    assert assessment.is_high_risk is False
    assert assessment.requires_dual_insurance is False
    assert assessment.allow_always_blocked is False
    assert assessment.mutating_count == 0
    assert assessment.read_only_count == 1
    assert assessment.has_violations is False


def test_batch_read_only_tools_fast_pass():
    tool_calls = [
        {"name": "file_read", "args": {"path": f"/workspace/file_{i}.txt"}}
        for i in range(5)
    ]
    assessment = evaluate_batch_risk(tool_calls)
    assert assessment.is_batch is True
    assert assessment.batch_size == 5
    assert assessment.is_high_risk is False
    assert assessment.requires_dual_insurance is False
    assert assessment.allow_always_blocked is False
    assert assessment.mutating_count == 0
    assert assessment.read_only_count == 5


def test_batch_size_limit_exceeded():
    policy = DeviceSecurityPolicy(max_batch_size=5)
    tool_calls = [
        {"name": "file_read", "args": {"path": f"/workspace/file_{i}.txt"}}
        for i in range(10)
    ]
    assessment = evaluate_batch_risk(tool_calls, policy=policy)
    assert assessment.is_batch is True
    assert assessment.batch_size == 10
    assert assessment.is_high_risk is True
    assert any("exceeds maximum permitted limit" in r for r in assessment.reasons)


def test_destructive_batch_triggers_dual_insurance():
    tool_calls = [
        {"name": "file_delete", "args": {"path": f"/workspace/log_{i}.txt"}}
        for i in range(4)
    ]
    assessment = evaluate_batch_risk(tool_calls)
    assert assessment.is_batch is True
    assert assessment.batch_size == 4
    assert assessment.is_high_risk is True
    assert assessment.requires_dual_insurance is True
    assert assessment.allow_always_blocked is True
    assert assessment.mutating_count == 4
    assert any("mutating operations" in r for r in assessment.reasons)


def test_restricted_path_access_escalation():
    tool_calls = [
        {
            "name": "file_write",
            "args": {"path": "/workspace/.env", "content": "SECRET=1"},
        },
    ]
    assessment = evaluate_batch_risk(tool_calls)
    assert assessment.is_high_risk is True
    assert assessment.requires_dual_insurance is True
    assert assessment.allow_always_blocked is True
    assert any("sensitive protected paths" in r for r in assessment.reasons)


def test_intra_tool_compound_shell_command_risk():
    tool_calls = [
        {
            "name": "shell_exec",
            "args": {"command": "rm -rf /tmp/data && pkill -9 python && echo 'done'"},
        }
    ]
    assessment = evaluate_batch_risk(tool_calls)
    assert (
        assessment.is_batch is True
    )  # Compound command with multiple high-risk verbs counted as batch
    assert assessment.is_high_risk is True
    assert assessment.requires_dual_insurance is True
    assert assessment.allow_always_blocked is True
    assert any("high-risk destructive operations" in r for r in assessment.reasons)


def test_custom_permission_resolver_integration():
    def custom_resolver(name: str, args: dict[str, object]) -> str:
        if name == "custom_bulk_reboot":
            return "system_manage"
        return "unknown"

    tool_calls = [
        {"name": "custom_bulk_reboot", "args": {"target": "node-1"}},
        {"name": "custom_bulk_reboot", "args": {"target": "node-2"}},
        {"name": "custom_bulk_reboot", "args": {"target": "node-3"}},
    ]
    assessment = evaluate_batch_risk(
        tool_calls,
        permission_resolver=custom_resolver,
    )
    assert assessment.is_batch is True
    assert assessment.mutating_count == 3
    assert assessment.requires_dual_insurance is True
