"""Unit tests for HITL Denial Events and Synthetic Tool Result suite.

[POS]
Harness core security test suite verifying AgentScope-Java #2546 HITL denial handling,
synthetic ToolResult emission, and AllToolsDenied policy gating.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.hitl_denial import (
    DenialResolutionPolicy,
    HitlDenialManager,
    SyntheticToolResultBlock,
    ToolDenialItem,
)


def test_format_denial_message() -> None:
    manager = HitlDenialManager()

    item_simple = ToolDenialItem(
        tool_call_id="call_123",
        tool_name="bash_exec",
        reason="Command rm -rf is prohibited",
    )
    msg_simple = manager.format_denial_message(item_simple)
    assert "[Action Denied by User]" in msg_simple
    assert "Tool 'bash_exec' execution was rejected" in msg_simple
    assert "Reason: Command rm -rf is prohibited" in msg_simple

    item_feedback = ToolDenialItem(
        tool_call_id="call_456",
        tool_name="database_drop",
        reason="Production DB protection",
        custom_feedback="Please run dry-run select query instead",
    )
    msg_feedback = manager.format_denial_message(item_feedback)
    assert "User Guidance: Please run dry-run select query instead" in msg_feedback


def test_process_partial_denials_continue_policy() -> None:
    manager = HitlDenialManager(
        default_all_denied_policy=DenialResolutionPolicy.CONTINUE
    )

    denied = [
        ToolDenialItem(
            tool_call_id="call_1",
            tool_name="file_delete",
            reason="Do not delete config",
        )
    ]

    res = manager.process_denials(denied_items=denied, total_tool_calls_in_step=2)
    assert res.all_tools_denied is False
    assert res.total_requested == 2
    assert res.total_denied == 1
    assert res.stop_requested is False
    assert len(res.synthetic_results) == 1

    synth = res.synthetic_results[0]
    assert synth.tool_call_id == "call_1"
    assert synth.is_error is True
    assert synth.metadata["denied_by"] == "human_in_the_loop"


def test_process_all_denials_stop_policy() -> None:
    manager = HitlDenialManager(default_all_denied_policy=DenialResolutionPolicy.STOP)

    denied = [
        ToolDenialItem(tool_call_id="call_a", tool_name="format_disk"),
        ToolDenialItem(tool_call_id="call_b", tool_name="wipe_logs"),
    ]

    res = manager.process_denials(denied_items=denied, total_tool_calls_in_step=2)
    assert res.all_tools_denied is True
    assert res.total_requested == 2
    assert res.total_denied == 2
    assert res.resolution_action == DenialResolutionPolicy.STOP
    assert res.stop_requested is True
    assert len(res.synthetic_results) == 2


def test_override_policy_on_demand() -> None:
    manager = HitlDenialManager(default_all_denied_policy=DenialResolutionPolicy.STOP)

    denied = [ToolDenialItem(tool_call_id="call_c", tool_name="transfer_funds")]

    # Override with CONTINUE even when all tools denied
    res = manager.process_denials(
        denied_items=denied,
        total_tool_calls_in_step=1,
        override_policy=DenialResolutionPolicy.CONTINUE,
    )
    assert res.all_tools_denied is True
    assert res.resolution_action == DenialResolutionPolicy.CONTINUE
    assert res.stop_requested is False
