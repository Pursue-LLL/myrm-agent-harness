"""Unit tests for interactive plan mode pre-execution review and state boundary locker.

Verifies:
1. Tool read-only classification (whitelist inspection vs write/destructive blocking).
2. Static tool exposure filtering across PLAN vs ACT modes.
3. Runtime fail-closed tool call interception in Plan Mode.
4. Implementation plan contract formulation, Markdown review rendering, and JSON serialization.
5. Atomic approval transition to Act Mode and approved directive generation.
6. Re-entry into Plan Mode and state resetting.
"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.runtime.context.plan_mode_boundary_locker import (
    ExecutionMode,
    ImplementationPlanContract,
    PlanModeBoundaryLocker,
    filter_tools_for_mode,
    is_read_only_tool,
)


@dataclass
class _DummyTool:
    name: str


def test_is_read_only_tool_classification() -> None:
    # Read-only tools
    assert is_read_only_tool("view_file") is True
    assert is_read_only_tool("read_file") is True
    assert is_read_only_tool("grep_search") is True
    assert is_read_only_tool("glob_tool") is True
    assert is_read_only_tool("search_web") is True
    assert is_read_only_tool("get_status") is True
    assert is_read_only_tool("cat_file") is True

    # Mutating / write tools
    assert is_read_only_tool("write_to_file") is False
    assert is_read_only_tool("replace_file_content") is False
    assert is_read_only_tool("edit_file") is False
    assert is_read_only_tool("delete_file") is False
    assert is_read_only_tool("run_command") is False
    assert is_read_only_tool("execute_bash") is False
    assert is_read_only_tool("shell_cmd") is False

    # Edge cases
    assert is_read_only_tool("") is False
    assert is_read_only_tool("unknown_foo") is False


def test_filter_tools_for_mode() -> None:
    tools = [
        _DummyTool(name="read_file"),
        _DummyTool(name="view_file"),
        _DummyTool(name="write_to_file"),
        _DummyTool(name="replace_file_content"),
        _DummyTool(name="grep_search"),
    ]

    # In ACT mode, all tools are preserved
    act_tools = filter_tools_for_mode(tools, ExecutionMode.ACT)
    assert len(act_tools) == 5

    # In PLAN mode, only read-only tools are retained
    plan_tools = filter_tools_for_mode(tools, ExecutionMode.PLAN)
    assert len(plan_tools) == 3
    names = [t.name for t in plan_tools]
    assert names == ["read_file", "view_file", "grep_search"]


def test_runtime_boundary_locker_interception() -> None:
    locker = PlanModeBoundaryLocker(initial_mode=ExecutionMode.PLAN)
    assert locker.current_mode == ExecutionMode.PLAN

    # Read tool allowed in Plan Mode
    blocked, msg = locker.intercept_tool_call("view_file")
    assert blocked is False
    assert msg == ""

    # Write tool blocked in Plan Mode
    blocked, msg = locker.intercept_tool_call("write_to_file")
    assert blocked is True
    assert "PlanModeWriteBlocked" in msg
    assert "write_to_file" in msg


def test_plan_submission_and_markdown_review() -> None:
    locker = PlanModeBoundaryLocker(initial_mode=ExecutionMode.PLAN)

    plan = ImplementationPlanContract(
        title="Refactor Database Models",
        summary="Convert all declarative models to SQLAlchemy 2.0 mapped_column format.",
        steps=[
            {"id": "1", "description": "Update Base class definition", "verification": "Check imports"},
            {"id": "2", "description": "Update User and Post models", "verification": "Run pytest tests/models"},
        ],
        affected_files=["src/db/base.py", "src/models/user.py", "src/models/post.py"],
        risks_and_mitigations=["Risk: Alembic migration drift. Mitigation: dry-run alembic check."],
    )

    locker.submit_plan(plan)
    assert locker.current_plan is not None
    assert locker.current_plan.approved is False

    md = plan.to_markdown()
    assert "# Implementation Plan: Refactor Database Models" in md
    assert "1. Update Base class definition [Verify: Check imports]" in md
    assert "- `src/db/base.py`" in md
    assert "PENDING USER REVIEW" in md
    assert "**Status**:" in md


def test_approve_and_transition_to_act_mode() -> None:
    locker = PlanModeBoundaryLocker(initial_mode=ExecutionMode.PLAN)

    plan = ImplementationPlanContract(
        title="Payment Service Integration",
        summary="Add Stripe checkout endpoint.",
        steps=[{"id": "1", "description": "Create stripe webhook handler"}],
        affected_files=["api/payment.py"],
    )
    locker.submit_plan(plan)

    directive = locker.approve_and_transition_to_act(review_notes="Make sure to use test API keys only")
    assert locker.current_mode == ExecutionMode.ACT
    assert locker.current_plan is not None
    assert locker.current_plan.approved is True
    assert locker.current_plan.review_notes == "Make sure to use test API keys only"

    # In Act Mode, write tools are no longer blocked
    blocked, msg = locker.intercept_tool_call("write_to_file")
    assert blocked is False
    assert msg == ""

    # Directive contains formatted plan
    assert "<approved-implementation-plan>" in directive
    assert "ACT MODE" in directive
    assert "Make sure to use test API keys only" in directive
    assert "**Status**:  APPROVED" in directive


def test_reenter_plan_mode_resets_state() -> None:
    locker = PlanModeBoundaryLocker(initial_mode=ExecutionMode.ACT)
    assert locker.current_mode == ExecutionMode.ACT

    # Re-entering plan mode
    locker.enter_plan_mode()
    assert locker.current_mode == ExecutionMode.PLAN

    # Writing is blocked again
    blocked, msg = locker.intercept_tool_call("replace_file_content")
    assert blocked is True
    assert "PlanModeWriteBlocked" in msg
