"""Tests for DW preflight helpers and approval gate."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.dynamic_workflow import (
    WorkflowPlanReview,
    count_spawn_calls,
    format_plan_preview,
    run_dynamic_workflow_stream,
)
from myrm_agent_harness.agent.dynamic_workflow.preflight import (
    estimate_workflow_cost,
    resume_action,
    strip_script_markdown,
)


def test_count_spawn_calls_static():
    script = """
import myrm_tools
myrm_tools.spawn_subagent(task_id="a", agent_type="generalPurpose", task_description="x")
myrm_tools.spawn_subagent(task_id="b", agent_type="generalPurpose", task_description="y")
"""
    assert count_spawn_calls(script) == 2


def test_format_plan_preview_includes_literal_and_hard_cap():
    review = WorkflowPlanReview(
        script_code="print('x')",
        spawn_count=3,
        estimated_cost_usd=1.5,
        remaining_budget_usd=10.0,
        cost_status="configured_max_cost",
    )
    preview = format_plan_preview(review)
    assert "3 literal spawn" in preview
    assert "Runtime hard cap: 50 spawns" in preview
    assert "max 5 concurrent" in preview


def test_strip_script_markdown():
    assert strip_script_markdown("```python\nprint(1)\n```") == "print(1)"
    assert strip_script_markdown("```\ncode\n```") == "code"


def test_format_plan_preview_without_cost():
    review = WorkflowPlanReview(
        script_code="x = 1",
        spawn_count=1,
        estimated_cost_usd=None,
        remaining_budget_usd=None,
        cost_status="unavailable",
    )
    preview = format_plan_preview(review)
    assert "Cost estimate unavailable" in preview


def test_resume_action():
    assert resume_action(None) is None
    assert resume_action({"action": "confirm"}) == "confirm"
    assert resume_action({"action": 1}) is None


@pytest.mark.asyncio
async def test_estimate_workflow_cost_with_catalog():
    from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

    parent = MagicMock()
    catalog = AsyncMock()
    catalog.resolve.return_value = SubagentConfig(
        system_prompt="sub",
        max_cost_usd=1.0,
    )

    cost, _remaining, status = await estimate_workflow_cost(parent, catalog, 2, "audit apis")
    assert cost == 2.0
    assert status == "configured_max_cost"

    none_cost, _, no_spawn_status = await estimate_workflow_cost(parent, catalog, 0, "q")
    assert none_cost is None
    assert no_spawn_status == "no_spawns"


@pytest.mark.asyncio
async def test_estimate_workflow_cost_unavailable():
    parent = MagicMock()
    catalog = AsyncMock()
    catalog.resolve.return_value = None

    cost, _remaining, status = await estimate_workflow_cost(parent, catalog, 1, "task")
    assert cost is None
    assert status == "agent_config_unavailable"


@pytest.mark.asyncio
async def test_estimate_workflow_cost_exception():
    parent = MagicMock()
    catalog = AsyncMock()
    catalog.resolve.side_effect = RuntimeError("boom")

    cost, _remaining, status = await estimate_workflow_cost(parent, catalog, 1, "task")
    assert cost is None
    assert status == "unavailable"


@pytest.mark.asyncio
async def test_resume_skip_cancels_without_ptc(tmp_path, monkeypatch):
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    parent = MagicMock()
    parent.llm = AsyncMock()
    parent._cached_tools = []
    parent.user_tools = []

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=parent,
            query="skip me",
            chat_history=[],
            chat_id="c_skip",
            message_id="m_skip",
            resume_value={"action": "skip"},
        )
    ]

    end = next(c for c in chunks if c.get("type") == "message_end")
    assert end["completion_status"] == "cancelled"
    parent.llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_resume_confirm_missing_script_errors(tmp_path, monkeypatch):
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    parent = MagicMock()
    parent.llm = AsyncMock()
    parent._cached_tools = []
    parent.user_tools = []

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=parent,
            query="resume",
            chat_history=[],
            chat_id="c_miss",
            message_id="m_miss",
            resume_value={"action": "confirm"},
        )
    ]

    end = next(c for c in chunks if c.get("type") == "message_end")
    assert end["completion_status"] == "error"


@pytest.mark.asyncio
async def test_preflight_rejected_stops_before_ptc(tmp_path, monkeypatch):
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    script = """
import myrm_tools
myrm_tools.spawn_subagent(task_id="t1", agent_type="generalPurpose", task_description="do work")
print("done")
"""
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content=script)

    parent = MagicMock()
    parent.llm = llm
    parent._cached_tools = []
    parent.user_tools = []

    ptc_called = False

    async def mock_ptc(*args, **kwargs):
        nonlocal ptc_called
        ptc_called = True
        raise AssertionError("PTC should not run when approval rejected")

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    async def reject_gate(_review: WorkflowPlanReview) -> bool:
        return False

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=parent,
            query="test query",
            chat_history=[],
            chat_id="chat1",
            message_id="msg1",
            approval_gate=reject_gate,
        )
    ]

    assert ptc_called is False
    plan_events = [
        c
        for c in chunks
        if c.get("type") == "status"
        and isinstance(c.get("data"), dict)
        and c["data"].get("phase") == "plan_confirm"
    ]
    assert any(e["data"].get("status") == "waiting" for e in plan_events)
    end = next(c for c in chunks if c.get("type") == "message_end")
    assert end["completion_status"] == "cancelled"


@pytest.mark.asyncio
async def test_preflight_approved_runs_ptc(tmp_path, monkeypatch):
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    script = 'print("hello")'
    llm = AsyncMock()
    llm.ainvoke.side_effect = [
        AIMessage(content=script),
        AIMessage(content="summary"),
    ]

    parent = MagicMock()
    parent.llm = llm
    parent._cached_tools = []
    parent.user_tools = []

    class MockExecResult:
        stdout = "hello"
        stderr = ""

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        return MockExecResult()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    async def approve_gate(_review: WorkflowPlanReview) -> bool:
        return True

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=parent,
            query="test",
            chat_history=[],
            chat_id="c2",
            message_id="m2",
            approval_gate=approve_gate,
        )
    ]

    end = next(c for c in chunks if c.get("type") == "message_end")
    assert end["completion_status"] == "success"
