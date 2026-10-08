"""Comprehensive test suite for HITL Denial Events and Workflow Controls."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.hitl_denial_events import (
    DEFAULT_APPROVAL_MESSAGE,
    DEFAULT_DENIAL_REASON,
    AllToolsDeniedPolicy,
    AllToolsDeniedPolicyEvaluator,
    ConfirmResult,
    HitlDenialEventDispatcher,
    ToolResultState,
    ToolUseBlock,
)


@pytest.fixture
def sample_tools() -> list[ToolUseBlock]:
    return [
        ToolUseBlock(
            id="call_1",
            name="file_writer",
            arguments={"path": "/tmp/test.txt"},
        ),
        ToolUseBlock(
            id="call_2",
            name="bash_exec",
            arguments={"cmd": "echo 1"},
        ),
    ]


def test_custom_denial_reason_emitted(sample_tools: list[ToolUseBlock]) -> None:
    dispatcher = HitlDenialEventDispatcher()
    decisions = [
        ConfirmResult(
            tool_call_id="call_1",
            tool_name="file_writer",
            confirmed=False,
            reason="Writing to root directory is strictly prohibited.",
        ),
        ConfirmResult(
            tool_call_id="call_2",
            tool_name="bash_exec",
            confirmed=True,
        ),
    ]

    outcome = dispatcher.process_decisions(
        session_id="sess_01",
        step_id="step_01",
        tool_calls=sample_tools,
        decisions=decisions,
    )

    assert outcome.total_calls == 2
    assert outcome.confirmed_count == 1
    assert outcome.denied_count == 1
    assert outcome.all_denied is False
    assert outcome.can_resume is True
    assert outcome.all_tools_denied_event is None

    denied_event = outcome.tool_result_events[0]
    assert denied_event.tool_call_id == "call_1"
    assert denied_event.state == ToolResultState.DENIED
    assert (
        denied_event.output_text
        == "Writing to root directory is strictly prohibited."
    )

    allowed_event = outcome.tool_result_events[1]
    assert allowed_event.tool_call_id == "call_2"
    assert allowed_event.state == ToolResultState.ALLOWED
    assert allowed_event.output_text == DEFAULT_APPROVAL_MESSAGE


def test_default_denial_reason_when_unspecified(
    sample_tools: list[ToolUseBlock],
) -> None:
    dispatcher = HitlDenialEventDispatcher()
    decisions = [
        ConfirmResult(
            tool_call_id="call_1",
            tool_name="file_writer",
            confirmed=False,
            reason=None,
        ),
        ConfirmResult(
            tool_call_id="call_2",
            tool_name="bash_exec",
            confirmed=False,
            reason="   ",
        ),
    ]

    outcome = dispatcher.process_decisions(
        session_id="sess_02",
        step_id="step_01",
        tool_calls=sample_tools,
        decisions=decisions,
    )

    assert outcome.all_denied is True
    assert outcome.denied_count == 2
    assert len(outcome.tool_result_events) == 2
    for event in outcome.tool_result_events:
        assert event.state == ToolResultState.DENIED
        assert event.output_text == DEFAULT_DENIAL_REASON


def test_all_tools_denied_halt_policy(sample_tools: list[ToolUseBlock]) -> None:
    dispatcher = HitlDenialEventDispatcher()
    decisions = [
        ConfirmResult(
            tool_call_id="call_1",
            tool_name="file_writer",
            confirmed=False,
            reason="Forbidden destination",
        ),
        ConfirmResult(
            tool_call_id="call_2",
            tool_name="bash_exec",
            confirmed=False,
            reason="Subprocess banned",
        ),
    ]

    outcome = dispatcher.process_decisions(
        session_id="sess_03",
        step_id="step_01",
        tool_calls=sample_tools,
        decisions=decisions,
        explicit_policy=AllToolsDeniedPolicy.HALT,
    )

    assert outcome.all_denied is True
    assert outcome.can_resume is False
    assert outcome.terminal_reason == "ALL_TOOLS_DENIED"
    assert outcome.all_tools_denied_event is not None
    assert outcome.all_tools_denied_event.should_stop is True
    assert outcome.all_tools_denied_event.policy_applied == AllToolsDeniedPolicy.HALT


def test_all_tools_denied_resume_policy(sample_tools: list[ToolUseBlock]) -> None:
    dispatcher = HitlDenialEventDispatcher()
    decisions = [
        ConfirmResult(
            tool_call_id="call_1",
            tool_name="file_writer",
            confirmed=False,
            reason="Try reading first instead",
        ),
        ConfirmResult(
            tool_call_id="call_2",
            tool_name="bash_exec",
            confirmed=False,
            reason="Command not necessary",
        ),
    ]

    outcome = dispatcher.process_decisions(
        session_id="sess_04",
        step_id="step_01",
        tool_calls=sample_tools,
        decisions=decisions,
        explicit_policy=AllToolsDeniedPolicy.RESUME_WITH_FEEDBACK,
    )

    assert outcome.all_denied is True
    assert outcome.can_resume is True
    assert outcome.terminal_reason is None
    assert outcome.all_tools_denied_event is not None
    assert outcome.all_tools_denied_event.should_stop is False
    assert (
        outcome.all_tools_denied_event.policy_applied
        == AllToolsDeniedPolicy.RESUME_WITH_FEEDBACK
    )


def test_strict_halt_tool_override() -> None:
    evaluator = AllToolsDeniedPolicyEvaluator(
        default_policy=AllToolsDeniedPolicy.RESUME_WITH_FEEDBACK,
        strict_halt_tools=["dangerous_shell"],
    )
    dispatcher = HitlDenialEventDispatcher(policy_evaluator=evaluator)

    tools = [
        ToolUseBlock(
            id="call_danger",
            name="dangerous_shell",
            arguments={},
        ),
    ]
    decisions = [
        ConfirmResult(
            tool_call_id="call_danger",
            tool_name="dangerous_shell",
            confirmed=False,
            reason="Blocked dangerous shell",
        ),
    ]

    outcome = dispatcher.process_decisions(
        session_id="sess_05",
        step_id="step_01",
        tool_calls=tools,
        decisions=decisions,
        explicit_policy=AllToolsDeniedPolicy.RESUME_WITH_FEEDBACK,
    )

    assert outcome.all_denied is True
    assert outcome.can_resume is False
    assert outcome.terminal_reason == "ALL_TOOLS_DENIED_CRITICAL_TOOL_DANGEROUS_SHELL"
    assert outcome.all_tools_denied_event is not None
    assert outcome.all_tools_denied_event.should_stop is True
