"""Unit tests for Prompt Cache Dynamic Roll-Forward and Headless 3D Sandbox Suite (Item 330)."""

from pathlib import Path
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward import (
    AnomalyGuardStatus,
    DynamicRollForwardEngine,
    Headless3DEngineType,
    Headless3DScriptRequest,
    PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite,
    RollForwardStrategy,
    validate_3d_script_safety,
)


def test_dynamic_roll_forward_engine_basic_strip_and_advance() -> None:
    """Verify intermediate breakpoints are stripped and the newest tool message receives cache_control."""
    engine = DynamicRollForwardEngine(
        strategy=RollForwardStrategy.STRIP_INTERMEDIATE,
        enable_1h_ttl=True,
    )

    # Initial conversation state before tool execution
    messages = [
        SystemMessage(content="You are a 3D geometry engineer.", additional_kwargs={"cache_control": {"type": "ephemeral", "ttl": "1h"}}),
        HumanMessage(content="Create a parametric gear model."),
        AIMessage(
            content="",
            additional_kwargs={
                "tool_calls": [{"id": "call_1", "function": {"name": "blender_exec_script", "arguments": "{}"}}],
                "cache_control": {"type": "ephemeral"},  # Old transient breakpoint from prior turn
            },
        ),
        ToolMessage(content="Gear base mesh generated", tool_call_id="call_1"),
        AIMessage(
            content="",
            additional_kwargs={
                "tool_calls": [{"id": "call_2", "function": {"name": "blender_exec_script", "arguments": "{}"}}],
            },
        ),
        ToolMessage(content="Chamfer bevel modifier applied successfully", tool_call_id="call_2"),
    ]

    new_messages, result = engine.roll_forward(messages)

    # 1. Total messages checked
    assert result.total_messages == 6
    # 2. SystemMessage at index 0 must retain cache_control
    assert "cache_control" in new_messages[0].additional_kwargs
    assert new_messages[0].additional_kwargs["cache_control"]["ttl"] == "1h"
    assert 0 in result.preserved_permanent_indices

    # 3. Intermediate AIMessage at index 2 must have its obsolete cache_control stripped
    assert "cache_control" not in new_messages[2].additional_kwargs

    # 4. Old ToolMessage at index 3 must not carry cache_control
    assert "cache_control" not in new_messages[3].additional_kwargs

    # 5. Newest ToolMessage at index 5 must receive rolled-forward cache_control
    assert result.rolled_forward_index == 5
    assert "cache_control" in new_messages[5].additional_kwargs
    assert new_messages[5].additional_kwargs["cache_control"]["type"] == "ephemeral"
    assert new_messages[5].additional_kwargs["cache_control"]["ttl"] == "1h"

    # 6. Total active breakpoints must be strictly <= 4
    assert len(result.new_active_breakpoint_indices) <= 4
    assert set(result.new_active_breakpoint_indices) == {0, 5}


def test_dynamic_roll_forward_engine_max_breakpoints_ceiling() -> None:
    """Verify breakpoint ceiling (<= 4) is strictly enforced when multiple permanent anchors exist."""
    engine = DynamicRollForwardEngine(max_breakpoints=4)

    # Create 6 messages, simulate multiple permanent breakpoints requested
    messages = [
        SystemMessage(content="System prompt", additional_kwargs={"cache_control": {"type": "ephemeral"}}),
        HumanMessage(content="Doc A", additional_kwargs={"cache_control": {"type": "ephemeral"}}),
        HumanMessage(content="Doc B", additional_kwargs={"cache_control": {"type": "ephemeral"}}),
        HumanMessage(content="Doc C", additional_kwargs={"cache_control": {"type": "ephemeral"}}),
        HumanMessage(content="Doc D", additional_kwargs={"cache_control": {"type": "ephemeral"}}),
        ToolMessage(content="Tool result", tool_call_id="call_x"),
    ]

    new_messages, result = engine.roll_forward(messages, permanent_indices=[0, 1, 2, 3, 4])

    # Must be pruned down to <= 4 breakpoints
    assert len(result.new_active_breakpoint_indices) == 4
    # The newest tool message at index 5 must be kept
    assert 5 in result.new_active_breakpoint_indices
    # The primary system prompt at index 0 must be kept
    assert 0 in result.new_active_breakpoint_indices


def test_cache_miss_anomaly_guard_fusing_and_reset() -> None:
    """Verify consecutive catastrophic cache misses trip the circuit breaker."""
    suite = PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite()

    # Round 1: normal cache hit (e.g. 50k tokens, 48k cached)
    r1 = suite.record_round_tokens(round_index=1, input_tokens=50_000, cache_read_tokens=48_000)
    assert r1.status == AnomalyGuardStatus.NORMAL
    assert not suite.is_circuit_broken

    # Round 2: 1st severe cold miss (input > 20k, cache read == 0) -> WARNING
    r2 = suite.record_round_tokens(round_index=2, input_tokens=35_000, cache_read_tokens=0)
    assert r2.status == AnomalyGuardStatus.WARNING
    assert r2.consecutive_cold_misses == 1
    assert not suite.is_circuit_broken

    # Round 3: 2nd consecutive severe cold miss -> TRIP CIRCUIT BREAKER
    r3 = suite.record_round_tokens(round_index=3, input_tokens=42_000, cache_read_tokens=0)
    assert r3.status == AnomalyGuardStatus.FUSED_CIRCUIT_BROKEN
    assert r3.is_circuit_broken is True
    assert suite.is_circuit_broken is True
    assert "circuit breaker tripped" in r3.reason.lower()

    # Reset circuit breaker
    suite.reset_anomaly_guard()
    assert not suite.is_circuit_broken


def test_headless_3d_sandbox_adapter_safety_and_execution(tmp_path: Path) -> None:
    """Verify AST security screening and deterministic headless 3D simulation."""
    suite = PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite(
        sandbox_workspace=tmp_path
    )

    # 1. Unsafe script rejected by AST static check
    unsafe_script = """
import os
os.system("rm -rf /")
"""
    is_safe, reason = validate_3d_script_safety(unsafe_script)
    assert is_safe is False
    assert "Prohibited function execution" in reason or "Prohibited module import" in reason

    req_unsafe = Headless3DScriptRequest(
        engine=Headless3DEngineType.BLENDER,
        script_content=unsafe_script,
        target_artifact_name="unsafe_gear",
    )
    res_unsafe = suite.execute_3d_script(req_unsafe)
    assert res_unsafe.success is False
    assert "Security rejection" in res_unsafe.stderr_summary

    # 2. Safe Blender Python modeling script executed in simulation/CPU mode
    safe_script = """
import bpy
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
"""
    req_safe = Headless3DScriptRequest(
        engine=Headless3DEngineType.BLENDER,
        script_content=safe_script,
        output_format="gltf",
        target_artifact_name="gear_v1",
        render_preview=True,
    )
    res_safe = suite.execute_3d_script(req_safe, mock_in_test=True)
    assert res_safe.success is True
    assert res_safe.return_code == 0
    assert "gear_v1.gltf" in res_safe.generated_3d_file
    assert "gear_v1_preview.png" in res_safe.rendered_preview_png
    assert Path(res_safe.generated_3d_file).exists()
    assert Path(res_safe.rendered_preview_png).exists()


def test_long_task_telemetry_tracker_hud() -> None:
    """Verify iteration milestones (V1 -> V10 -> V13) and aggregated HUD telemetry."""
    suite = PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite(
        task_id="autonomous_cad_3h",
        weekly_quota_tokens=20_000_000,
    )

    # Iteration V1
    s1 = suite.record_task_iteration(
        iteration_label="V1",
        tool_round_index=1,
        input_tokens=100_000,
        cache_read_tokens=90_000,
        cost_saved_usd=0.243,
        preview_artifact_path="/tmp/v1.png",
    )
    assert s1.cache_hit_rate == 0.90

    # Iteration V10
    suite.record_task_iteration(
        iteration_label="V10",
        tool_round_index=10,
        input_tokens=150_000,
        cache_read_tokens=140_000,
        cost_saved_usd=0.378,
        preview_artifact_path="/tmp/v10.png",
    )

    # Iteration V13
    suite.record_task_iteration(
        iteration_label="V13",
        tool_round_index=13,
        input_tokens=180_000,
        cache_read_tokens=175_000,
        cost_saved_usd=0.472,
        preview_artifact_path="/tmp/v13.png",
    )

    hud = suite.get_telemetry_hud()
    assert hud["current_version"] == "V13"
    assert hud["total_iterations"] == 3
    assert hud["total_input_tokens"] == 430_000
    assert hud["total_cache_read_tokens"] == 405_000
    assert float(hud["overall_cache_hit_rate"]) > 0.94
    assert hud["latest_preview_path"] == "/tmp/v13.png"
    assert len(hud["recent_trend"]) == 3


def test_prompt_cache_roll_forward_suite_end_to_end() -> None:
    """End-to-end integration: tool loop message roll forward, token auditing, and telemetry."""
    suite = PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite(
        task_id="e2e_parametric_engine",
    )

    # Round 1: Generate initial mesh
    msgs = [
        SystemMessage(content="You are a 3D generative agent."),
        HumanMessage(content="Model an impeller blade."),
    ]
    # Advance cache breakpoint before 1st model call
    msgs, res1 = suite.advance_cache_breakpoints(msgs)
    assert res1.rolled_forward_index == 1

    # Simulate Tool execution returning ToolMessage
    msgs.append(AIMessage(content="", additional_kwargs={"tool_calls": [{"id": "c1", "function": {"name": "run"}}]}))
    msgs.append(ToolMessage(content="Blade V1 created", tool_call_id="c1"))

    # Advance cache breakpoint before 2nd model call (Roll forward to newest ToolMessage)
    msgs, res2 = suite.advance_cache_breakpoints(msgs)
    assert res2.rolled_forward_index == 3
    assert "cache_control" in msgs[3].additional_kwargs

    # Audit tokens for round 1
    report = suite.record_round_tokens(round_index=1, input_tokens=80_000, cache_read_tokens=76_000)
    assert report.status == AnomalyGuardStatus.NORMAL

    # Log task milestone
    suite.record_task_iteration(
        iteration_label="V1",
        tool_round_index=1,
        input_tokens=80_000,
        cache_read_tokens=76_000,
        cost_saved_usd=0.205,
    )

    hud = suite.get_telemetry_hud()
    assert hud["current_version"] == "V1"
    assert not suite.is_circuit_broken
