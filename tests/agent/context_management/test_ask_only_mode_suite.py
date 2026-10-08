"""Unit tests for WorkBuddy Ask-Only mode, tool filtering, and token savings suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.ask_only_mode import (
    AskOnlyFilterResult,
    SessionInteractionMode,
    ToolDescriptor,
    ToolExecutionCheckResult,
    ToolSideEffectLevel,
    WorkBuddyAskOnlyModeSuite,
)


def _build_sample_tools() -> list[ToolDescriptor]:
    return [
        ToolDescriptor(
            name="search_code",
            description="Search codebase without side effects",
            side_effect_level=ToolSideEffectLevel.READ_ONLY,
            schema_token_cost=200,
        ),
        ToolDescriptor(
            name="read_document",
            description="Read local file contents",
            side_effect_level=ToolSideEffectLevel.READ_ONLY,
            schema_token_cost=150,
        ),
        ToolDescriptor(
            name="write_file",
            description="Overwrite or create file",
            side_effect_level=ToolSideEffectLevel.MUTATION_WRITE,
            schema_token_cost=300,
        ),
        ToolDescriptor(
            name="bash_executor",
            description="Execute arbitrary shell command",
            side_effect_level=ToolSideEffectLevel.MUTATION_EXECUTE,
            schema_token_cost=450,
        ),
    ]


def test_ask_only_mode_filters_mutation_tools_and_saves_tokens() -> None:
    """Test Ask-Only mode prunes mutation tools and computes saved schema token budget."""
    suite = WorkBuddyAskOnlyModeSuite(initial_mode=SessionInteractionMode.ASK_ONLY)
    tools = _build_sample_tools()
    suite.register_tools(tools)

    active_tools = suite.get_active_tools()
    assert len(active_tools) == 2
    assert {t.name for t in active_tools} == {"search_code", "read_document"}

    report: AskOnlyFilterResult = suite.evaluate_filter()
    assert report.mode == SessionInteractionMode.ASK_ONLY
    assert len(report.filtered_tools) == 2
    assert {t.name for t in report.filtered_tools} == {"write_file", "bash_executor"}
    # 300 + 450 = 750 tokens saved
    assert report.tokens_saved == 750
    assert "pruned 2 mutation/execution tool(s)" in report.filter_reason


def test_goal_execution_mode_preserves_all_tools() -> None:
    """Test Goal Execution mode preserves all registered tools with zero token savings."""
    suite = WorkBuddyAskOnlyModeSuite(initial_mode=SessionInteractionMode.GOAL_EXECUTION)
    tools = _build_sample_tools()
    suite.register_tools(tools)

    active_tools = suite.get_active_tools()
    assert len(active_tools) == 4
    assert {t.name for t in active_tools} == {"search_code", "read_document", "write_file", "bash_executor"}

    report = suite.evaluate_filter()
    assert report.mode == SessionInteractionMode.GOAL_EXECUTION
    assert len(report.filtered_tools) == 0
    assert report.tokens_saved == 0


def test_runtime_execution_interception_in_ask_only_mode() -> None:
    """Test runtime execution attempts of mutation tools are strictly blocked in Ask-Only mode."""
    suite = WorkBuddyAskOnlyModeSuite(initial_mode=SessionInteractionMode.ASK_ONLY)
    tools = _build_sample_tools()
    suite.register_tools(tools)

    # Read-only tool execution authorized
    res_read: ToolExecutionCheckResult = suite.check_and_authorize_execution("read_document")
    assert res_read.allowed is True
    assert res_read.violation_reason is None

    # Mutation execute tool blocked
    res_bash: ToolExecutionCheckResult = suite.check_and_authorize_execution("bash_executor")
    assert res_bash.allowed is False
    assert res_bash.violation_reason is not None
    assert "forbidden under Ask-Only mode" in res_bash.violation_reason

    # Mutation write tool blocked
    res_write: ToolExecutionCheckResult = suite.check_and_authorize_execution("write_file")
    assert res_write.allowed is False
    assert "forbidden under Ask-Only mode" in res_write.violation_reason

    # Verify blocked counter
    assert suite.total_blocked_executions == 2


def test_mode_switching_and_metrics_accumulation() -> None:
    """Test dynamic switching between Ask-Only and Goal Execution modes."""
    suite = WorkBuddyAskOnlyModeSuite(initial_mode=SessionInteractionMode.ASK_ONLY)
    tools = _build_sample_tools()
    suite.register_tools(tools)

    # 1. Ask-Only: bash blocked
    res1 = suite.check_and_authorize_execution("bash_executor")
    assert res1.allowed is False
    assert suite.total_blocked_executions == 1

    # 2. Switch to Goal Execution: bash now permitted
    suite.set_mode(SessionInteractionMode.GOAL_EXECUTION)
    assert suite.current_mode == SessionInteractionMode.GOAL_EXECUTION
    assert len(suite.get_active_tools()) == 4

    res2 = suite.check_and_authorize_execution("bash_executor")
    assert res2.allowed is True
    assert suite.total_blocked_executions == 1

    # 3. Switch back to Ask-Only: bash blocked again
    suite.set_mode(SessionInteractionMode.ASK_ONLY)
    assert len(suite.get_active_tools()) == 2

    res3 = suite.check_and_authorize_execution("bash_executor")
    assert res3.allowed is False
    assert suite.total_blocked_executions == 2
