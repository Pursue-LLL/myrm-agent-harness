"""Unit and integration tests for MidRunGraphPatchCompilerGate and Kahn DAG compilation.

[INPUT]
- myrm_agent_harness.agent.sub_agents.dag_plan::Plan, PlanStep, GraphPatch, GraphPatchResult
- myrm_agent_harness.agent.sub_agents.orchestrator::execute_dag_plan

[OUTPUT]
- Test suite verifying OCC optimistic lock, state immutability, dangling dependency rejection,
  Kahn cycle detection, topology-preserving fast-path, and runtime in-flight execution.

[POS]
Tests verifying mid-run dynamic graph patching guarantees in DAG orchestration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.sub_agents.dag_plan import (
    GraphPatch,
    Plan,
    PlanStep,
)
from myrm_agent_harness.agent.sub_agents.orchestrator import (
    _extract_graph_patch_data,
    execute_dag_plan,
)
from myrm_agent_harness.agent.sub_agents.types import SubAgentResult, SubAgentStatus


def test_graph_patch_occ_revision_conflict() -> None:
    plan = Plan(
        goal="Test goal",
        steps=[PlanStep(step_id="step1", description="Step 1")],
        revision=2,
    )
    patch = GraphPatch(
        base_revision=1,  # Stale revision
        add_steps=[PlanStep(step_id="step2", description="Step 2")],
    )

    result = plan.apply_graph_patch(patch)
    assert result.success is False
    assert result.new_revision == 2
    assert "Revision conflict" in (result.error or "")
    assert len(plan.steps) == 1


def test_graph_patch_immutability_terminal_and_running_steps() -> None:
    plan = Plan(
        goal="Test immutability",
        steps=[
            PlanStep(step_id="s1", description="Completed", status="completed"),
            PlanStep(step_id="s2", description="Running", status="in_progress"),
            PlanStep(step_id="s3", description="Pending", status="pending"),
        ],
        revision=1,
    )

    # 1. Attempt to remove completed step
    patch_del_completed = GraphPatch(base_revision=1, remove_steps=["s1"])
    res1 = plan.apply_graph_patch(patch_del_completed)
    assert res1.success is False
    assert "immutable status 'completed'" in (res1.error or "")

    # 2. Attempt to remove in-progress step
    patch_del_running = GraphPatch(base_revision=1, remove_steps=["s2"])
    res2 = plan.apply_graph_patch(patch_del_running)
    assert res2.success is False
    assert "immutable status 'in_progress'" in (res2.error or "")

    # 3. Attempt to modify dependencies of completed step
    patch_mod_completed = GraphPatch(
        base_revision=1, modify_dependencies={"s1": ["s3"]}
    )
    res3 = plan.apply_graph_patch(patch_mod_completed)
    assert res3.success is False
    assert "immutable status 'completed'" in (res3.error or "")


def test_graph_patch_add_remove_and_kahn_success() -> None:
    plan = Plan(
        goal="Test mutation",
        steps=[
            PlanStep(step_id="s1", description="S1", status="completed"),
            PlanStep(step_id="s2", description="S2", status="pending", dependencies=["s1"]),
        ],
        revision=1,
    )

    # Replace s2 with s2_new, and add s3 depending on s2_new
    patch = GraphPatch(
        base_revision=1,
        remove_steps=["s2"],
        add_steps=[
            PlanStep(step_id="s2_new", description="New S2", dependencies=["s1"]),
            PlanStep(step_id="s3", description="S3", dependencies=["s2_new"]),
        ],
    )

    res = plan.apply_graph_patch(patch)
    assert res.success is True
    assert res.new_revision == 2
    assert plan.revision == 2
    step_ids = [s.step_id for s in plan.steps]
    assert step_ids == ["s1", "s2_new", "s3"]

    # Ready steps should now find s2_new (since s1 is completed)
    ready = plan.get_ready_steps()
    assert [s.step_id for s in ready] == ["s2_new"]


def test_graph_patch_cycle_detection_kahn() -> None:
    plan = Plan(
        goal="Test cycle detection",
        steps=[PlanStep(step_id="s1", description="S1", status="completed")],
        revision=1,
    )

    # Add s2 depending on s3, and s3 depending on s2 (Cycle!)
    patch = GraphPatch(
        base_revision=1,
        add_steps=[
            PlanStep(step_id="s2", description="S2", dependencies=["s3"]),
            PlanStep(step_id="s3", description="S3", dependencies=["s2"]),
        ],
    )

    res = plan.apply_graph_patch(patch)
    assert res.success is False
    assert "Cycle detected" in (res.error or "")
    assert plan.revision == 1
    assert len(plan.steps) == 1


def test_graph_patch_dangling_dependency() -> None:
    plan = Plan(
        goal="Test dangling dep",
        steps=[PlanStep(step_id="s1", description="S1")],
        revision=1,
    )

    patch = GraphPatch(
        base_revision=1,
        add_steps=[
            PlanStep(step_id="s2", description="S2", dependencies=["non_existent_step"])
        ],
    )

    res = plan.apply_graph_patch(patch)
    assert res.success is False
    assert "Dangling dependency" in (res.error or "")
    assert plan.revision == 1


def test_graph_patch_topology_preserving_fast_path() -> None:
    plan = Plan(
        goal="Test fast path",
        steps=[PlanStep(step_id="s1", description="S1")],
        revision=1,
    )

    # Frontier extension: only append s2 depending on s1
    patch = GraphPatch(
        base_revision=1,
        add_steps=[PlanStep(step_id="s2", description="S2", dependencies=["s1"])],
    )

    res = plan.apply_graph_patch(patch)
    assert res.success is True
    assert res.topology_preserving is True
    assert res.new_revision == 2


@pytest.mark.asyncio
async def test_execute_dag_plan_applies_graph_patch_in_flight() -> None:
    """Verifies that execute_dag_plan dynamically incorporates a runtime GraphPatch."""
    plan = Plan(
        goal="Dynamic test",
        steps=[PlanStep(step_id="s1", description="Step 1", status="pending")],
        revision=1,
    )

    manager = MagicMock()

    # Step 1 returns a patch that dynamically adds Step 2
    patch_payload = {
        "base_revision": 1,
        "add_steps": [
            {
                "step_id": "s2",
                "description": "Step 2 added at runtime",
                "status": "pending",
                "dependencies": ["s1"],
            }
        ],
    }

    async def mock_spawn_child(*args, **kwargs):
        task_id = kwargs.get("task_id", "")
        if "s1" in task_id:
            return SubAgentResult(
                success=True,
                task_id=task_id,
                agent_type="general",
                result="Step 1 completed",
                payload={"graph_patch": patch_payload},
                status=SubAgentStatus.COMPLETED,
            )
        return SubAgentResult(
            success=True,
            task_id=task_id,
            agent_type="general",
            result="Step 2 completed",
            status=SubAgentStatus.COMPLETED,
        )

    manager.spawn_child = AsyncMock(side_effect=mock_spawn_child)
    manager._parent_agent = MagicMock()

    events_captured = []

    def progress_sink(step_id: str, status: str, message: str) -> None:
        events_captured.append((step_id, status, message))

    result = await execute_dag_plan(
        plan=plan,
        manager=manager,
        context={},
        tool_registry_getter=lambda: [],
        progress_sink=progress_sink,
    )

    assert result["success"] is True
    assert plan.revision == 2
    assert len(plan.steps) == 2
    assert plan.steps[0].status == "completed"
    assert plan.steps[1].status == "completed"

    # Confirm event was emitted
    applied_events = [
        e for e in events_captured if e[1] == "graph_patch_applied"
    ]
    assert len(applied_events) == 1
    assert "Graph patch applied v2" in applied_events[0][2]


def test_extract_graph_patch_data_direct_and_llm_text() -> None:
    # 1. Payload dict
    r1 = SubAgentResult(
        success=True,
        task_id="t1",
        agent_type="general",
        payload={"graph_patch": {"base_revision": 1, "remove_steps": ["s2"]}},
    )
    p1 = _extract_graph_patch_data(r1)
    assert p1 == {"base_revision": 1, "remove_steps": ["s2"]}

    # 2. Result dict
    r2 = SubAgentResult(
        success=True,
        task_id="t2",
        agent_type="general",
        result={"graph_patch": {"base_revision": 2, "remove_steps": ["s3"]}},
    )
    p2 = _extract_graph_patch_data(r2)
    assert p2 == {"base_revision": 2, "remove_steps": ["s3"]}

    # 3. LLM string output with <graph_patch>...</graph_patch>
    llm_output_tag = (
        "Investigation complete. Step 2 is obsolete, adding step 3.\n"
        "<graph_patch>\n"
        '{"base_revision": 1, "add_steps": [{"step_id": "s3", "description": "Verify DB"}]}\n'
        "</graph_patch>\n"
        "Proceeding with next actions."
    )
    r3 = SubAgentResult(
        success=True,
        task_id="t3",
        agent_type="general",
        result=llm_output_tag,
    )
    p3 = _extract_graph_patch_data(r3)
    assert p3 is not None
    assert p3["base_revision"] == 1
    assert len(p3["add_steps"]) == 1
    assert p3["add_steps"][0]["step_id"] == "s3"

    # 4. LLM string output with markdown fence json
    llm_output_json = (
        "Here is the patch:\n"
        "```json\n"
        '{"graph_patch": {"base_revision": 1, "remove_steps": ["s_old"]}}\n'
        "```"
    )
    r4 = SubAgentResult(
        success=True,
        task_id="t4",
        agent_type="general",
        result=llm_output_json,
    )
    p4 = _extract_graph_patch_data(r4)
    assert p4 == {"base_revision": 1, "remove_steps": ["s_old"]}

    # 5. Non-matching string returns None
    r5 = SubAgentResult(
        success=True,
        task_id="t5",
        agent_type="general",
        result="Just normal text without any patch.",
    )
    assert _extract_graph_patch_data(r5) is None


@pytest.mark.asyncio
async def test_execute_dag_plan_applies_llm_text_graph_patch_and_injects_revision() -> None:
    """Verifies that execute_dag_plan parses LLM <graph_patch> text and injects dag_plan_revision."""
    plan = Plan(
        goal="Dynamic test with LLM text",
        steps=[PlanStep(step_id="step_a", description="Step A", status="pending")],
        revision=1,
    )

    manager = MagicMock()
    captured_contexts: list[dict[str, object]] = []

    llm_reply_with_patch = (
        "Task completed.\n"
        "<graph_patch>\n"
        "{\n"
        '  "base_revision": 1,\n'
        '  "add_steps": [\n'
        '    {"step_id": "step_b", "description": "Step B dynamically added", "dependencies": ["step_a"]}\n'
        "  ]\n"
        "}\n"
        "</graph_patch>"
    )

    async def mock_spawn_child(*args, **kwargs):
        task_id = kwargs.get("task_id", "")
        captured_contexts.append(kwargs.get("context", {}))
        if "step_a" in task_id:
            return SubAgentResult(
                success=True,
                task_id=task_id,
                agent_type="general",
                result=llm_reply_with_patch,
                status=SubAgentStatus.COMPLETED,
            )
        return SubAgentResult(
            success=True,
            task_id=task_id,
            agent_type="general",
            result="Step B completed normally",
            status=SubAgentStatus.COMPLETED,
        )

    manager.spawn_child = AsyncMock(side_effect=mock_spawn_child)
    manager._parent_agent = MagicMock()

    events_captured: list[tuple[str, str, str]] = []

    def progress_sink(step_id: str, status: str, message: str) -> None:
        events_captured.append((step_id, status, message))

    result = await execute_dag_plan(
        plan=plan,
        manager=manager,
        context={"custom_key": "val"},
        tool_registry_getter=lambda: [],
        progress_sink=progress_sink,
    )

    assert result["success"] is True
    assert plan.revision == 2
    assert len(plan.steps) == 2
    assert plan.steps[0].status == "completed"
    assert plan.steps[1].status == "completed"
    assert plan.steps[1].step_id == "step_b"

    # Verify context injection
    assert len(captured_contexts) >= 1
    assert captured_contexts[0].get("dag_plan_revision") == 1

    applied_events = [e for e in events_captured if e[1] == "graph_patch_applied"]
    assert len(applied_events) == 1
    assert "Graph patch applied v2" in applied_events[0][2]

