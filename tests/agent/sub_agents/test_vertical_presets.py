"""Unit tests for Five Vertical Role Persona Presets and Sub-Bot Sandbox Tester (Item 64).

[INPUT]
- PresetsCatalog, SubBotSandboxTester, A2AFlowInspector, VerticalRolePreset.

[OUTPUT]
- Pytest assertions verifying preset registration, sandbox execution, and A2A communication loop detection.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_vertical_presets.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.vertical_presets import (
    A2AFlowInspector,
    A2AFlowStep,
    PresetsCatalog,
    ReasoningEffort,
    SubBotSandboxTester,
    SubBotTestRequest,
    SubBotTestResult,
    VerticalRoleCategory,
    VerticalRolePreset,
)


@pytest.fixture
def catalog() -> PresetsCatalog:
    """Fixture providing a fresh PresetsCatalog."""
    cat = PresetsCatalog()
    cat.reset_to_defaults()
    return cat


@pytest.fixture
def tester(catalog: PresetsCatalog) -> SubBotSandboxTester:
    """Fixture providing a SubBotSandboxTester instance."""
    return SubBotSandboxTester(catalog=catalog)


@pytest.fixture
def inspector() -> A2AFlowInspector:
    """Fixture providing an A2AFlowInspector instance."""
    insp = A2AFlowInspector()
    insp.clear()
    return insp


def test_builtin_presets_coverage(catalog: PresetsCatalog) -> None:
    """Verify all 5 core vertical presets are populated with proper fields."""
    presets = catalog.list_presets()
    assert len(presets) == 5

    categories = {p.category for p in presets}
    assert categories == {
        VerticalRoleCategory.LIFE_ADMIN,
        VerticalRoleCategory.OFFICE_MANAGER,
        VerticalRoleCategory.CLIPPER,
        VerticalRoleCategory.CHIEF_OF_STAFF,
        VerticalRoleCategory.SALES_TEAM,
    }

    life_admin = catalog.get_preset("life_admin")
    assert life_admin is not None
    assert life_admin.display_name == "Life Admin Specialist"
    assert len(life_admin.recommended_skills) > 0
    assert len(life_admin.recommended_tools) > 0
    assert life_admin.reasoning_effort == ReasoningEffort.LOW


def test_presets_catalog_filtering_and_registration(catalog: PresetsCatalog) -> None:
    """Verify catalog category filtering and custom preset registration."""
    clipper_list = catalog.list_presets(category=VerticalRoleCategory.CLIPPER)
    assert len(clipper_list) == 1
    assert clipper_list[0].role_id == "clipper"

    custom_preset = VerticalRolePreset(
        role_id="custom_specialist",
        category=VerticalRoleCategory.CHIEF_OF_STAFF,
        display_name="Custom Specialist",
        description="A specialized bot for testing.",
        persona_prompt="Custom persona prompt.",
    )
    catalog.register_preset(custom_preset)
    assert catalog.get_preset("custom_specialist") is not None
    assert len(catalog.list_presets()) == 6

    catalog.reset_to_defaults()
    assert len(catalog.list_presets()) == 5
    assert catalog.get_preset("custom_specialist") is None


def test_sub_bot_sandbox_tester_success(tester: SubBotSandboxTester) -> None:
    """Verify standard sandbox test execution for a built-in preset."""
    req = SubBotTestRequest(
        role_id="clipper",
        test_prompt="Summarize the latest research on vector databases.",
        mock_inputs={"query": "vector indexing"},
    )
    res = tester.run_test(req)

    assert res.success is True
    assert res.role_id == "clipper"
    assert "Knowledge Clipper & Distiller" in res.output_text
    assert len(res.tool_calls_made) > 0
    assert res.execution_time_ms >= 0.0
    assert len(res.logs) >= 3
    assert res.error_message is None


def test_sub_bot_sandbox_tester_unknown_role(tester: SubBotSandboxTester) -> None:
    """Verify test failure when targeting a non-existent role."""
    req = SubBotTestRequest(
        role_id="non_existent_bot",
        test_prompt="Hello world",
    )
    res = tester.run_test(req)

    assert res.success is False
    assert res.error_message == "Unknown role ID: non_existent_bot"
    assert "Error" in res.logs[0]


def test_sub_bot_sandbox_tester_custom_runner(tester: SubBotSandboxTester) -> None:
    """Verify sandbox custom runner invocation and exception handling."""
    def custom_runner(req: SubBotTestRequest) -> SubBotTestResult:
        return SubBotTestResult(
            test_id="custom_run",
            role_id=req.role_id,
            success=True,
            output_text="Custom runner output",
            execution_time_ms=1.5,
        )

    req = SubBotTestRequest(role_id="life_admin", test_prompt="Test custom")
    res = tester.run_test(req, custom_runner=custom_runner)
    assert res.success is True
    assert res.output_text == "Custom runner output"

    def crashing_runner(_: SubBotTestRequest) -> SubBotTestResult:
        raise ValueError("Runner crashed simulated")

    res_err = tester.run_test(req, custom_runner=crashing_runner)
    assert res_err.success is False
    assert "Runner crashed simulated" in (res_err.error_message or "")


def test_a2a_flow_inspector_record_and_clear(inspector: A2AFlowInspector) -> None:
    """Verify recording A2A flow steps and calculating cumulative duration."""
    session_id = "test-session-123"
    step1 = A2AFlowStep(
        step_id="step-1",
        source_agent_id="chief_of_staff",
        target_agent_id="clipper",
        action="delegate_research",
        payload_summary="Fetch vector indexing benchmarks",
        duration_ms=120.0,
    )
    step2 = A2AFlowStep(
        step_id="step-2",
        source_agent_id="clipper",
        target_agent_id="chief_of_staff",
        action="return_summary",
        payload_summary="Here is the distilled digest",
        duration_ms=80.0,
    )

    t1 = inspector.record_step(session_id, "chief_of_staff", step1)
    assert len(t1.steps) == 1
    assert t1.total_duration_ms == 120.0
    assert t1.is_loop_detected is False

    t2 = inspector.record_step(session_id, "chief_of_staff", step2)
    assert len(t2.steps) == 2
    assert t2.total_duration_ms == 200.0

    retrieved = inspector.get_trace(session_id)
    assert retrieved is not None
    assert len(retrieved.steps) == 2

    assert len(inspector.list_traces()) == 1
    inspector.clear()
    assert inspector.get_trace(session_id) is None


def test_a2a_flow_inspector_loop_detection(inspector: A2AFlowInspector) -> None:
    """Verify loop detection triggers when agents ping-pong indefinitely."""
    session_id = "loop-session-456"
    steps = [
        A2AFlowStep(step_id="s1", source_agent_id="agent_a", target_agent_id="agent_b", action="ask", payload_summary="1"),
        A2AFlowStep(step_id="s2", source_agent_id="agent_b", target_agent_id="agent_a", action="reply", payload_summary="2"),
        A2AFlowStep(step_id="s3", source_agent_id="agent_a", target_agent_id="agent_b", action="ask", payload_summary="3"),
        A2AFlowStep(step_id="s4", source_agent_id="agent_b", target_agent_id="agent_a", action="reply", payload_summary="4"),
    ]

    for s in steps:
        trace = inspector.record_step(session_id, "agent_a", s)

    assert trace.is_loop_detected is True


def test_a2a_flow_inspector_multi_node_cycle_and_linear(inspector: A2AFlowInspector) -> None:
    """Verify multi-node cycle detection via DFS graph analysis and non-cyclic linear chains."""
    linear_session = "linear-session-789"
    linear_steps = [
        A2AFlowStep(step_id="l1", source_agent_id="agent_a", target_agent_id="agent_b", action="step1", payload_summary=""),
        A2AFlowStep(step_id="l2", source_agent_id="agent_b", target_agent_id="agent_c", action="step2", payload_summary=""),
        A2AFlowStep(step_id="l3", source_agent_id="agent_c", target_agent_id="agent_d", action="step3", payload_summary=""),
        A2AFlowStep(step_id="l4", source_agent_id="agent_d", target_agent_id="agent_e", action="step4", payload_summary=""),
    ]
    for s in linear_steps:
        t = inspector.record_step(linear_session, "agent_a", s)
    assert t.is_loop_detected is False

    cycle_session = "cycle-session-999"
    cycle_steps = [
        A2AFlowStep(step_id="c1", source_agent_id="agent_a", target_agent_id="agent_b", action="step1", payload_summary=""),
        A2AFlowStep(step_id="c2", source_agent_id="agent_b", target_agent_id="agent_c", action="step2", payload_summary=""),
        A2AFlowStep(step_id="c3", source_agent_id="agent_c", target_agent_id="agent_d", action="step3", payload_summary=""),
        A2AFlowStep(step_id="c4", source_agent_id="agent_d", target_agent_id="agent_a", action="step4", payload_summary=""),
    ]
    for s in cycle_steps:
        t = inspector.record_step(cycle_session, "agent_a", s)
    assert t.is_loop_detected is True

