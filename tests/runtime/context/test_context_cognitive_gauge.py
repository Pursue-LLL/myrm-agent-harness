"""Unit tests for Context Cognitive Gauge and Agent Self-Awareness Meta-Tool.

Part of Item 125: InspectContextCognitiveGaugeMetaTool.
Verifies urgency tier transitions, remaining turns calculation, dynamic burn tracking,
LangChain BaseTool invocation, and thread safety.
"""

from __future__ import annotations

import concurrent.futures
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.runtime.context.context_cognitive_gauge import (
    ContextCognitiveGauge,
    create_inspect_context_tool,
)
from myrm_agent_harness.runtime.context.context_cognitive_gauge_types import (
    CognitiveActionGuidance,
    CognitiveGaugeConfig,
    ContextUrgencyLevel,
)


def test_urgency_level_and_action_guidance_tiers() -> None:
    """Verify tier transitions and guidance mappings across the context spectrum."""
    config = CognitiveGaugeConfig(
        max_context_tokens=100_000,
        converging_threshold_pct=60.0,
        critical_threshold_pct=85.0,
        exhausted_threshold_pct=95.0,
        default_turn_token_burn=2_000,
    )
    gauge = ContextCognitiveGauge(config=config)

    # 1. 30% used -> NOMINAL / EXPLORE_FREELY
    snap_30 = gauge.inspect(used_tokens=30_000)
    assert snap_30.capacity_pct == 30.0
    assert snap_30.remaining_tokens == 70_000
    assert snap_30.urgency_level == ContextUrgencyLevel.NOMINAL
    assert snap_30.suggested_action == CognitiveActionGuidance.EXPLORE_FREELY
    assert snap_30.estimated_remaining_turns == 35
    assert not snap_30.is_compaction_imminent
    assert "Headroom abundant" in snap_30.guidance_message

    # 2. 70% used -> CONVERGING / CONVERGE_AND_VERIFY
    snap_70 = gauge.inspect(used_tokens=70_000)
    assert snap_70.capacity_pct == 70.0
    assert snap_70.remaining_tokens == 30_000
    assert snap_70.urgency_level == ContextUrgencyLevel.CONVERGING
    assert snap_70.suggested_action == CognitiveActionGuidance.CONVERGE_AND_VERIFY
    assert "Begin converging subtasks" in snap_70.guidance_message

    # 3. 88% used -> CRITICAL / BRAKE_AND_SUMMARIZE
    snap_88 = gauge.inspect(used_tokens=88_000)
    assert snap_88.capacity_pct == 88.0
    assert snap_88.remaining_tokens == 12_000
    assert snap_88.urgency_level == ContextUrgencyLevel.CRITICAL
    assert snap_88.suggested_action == CognitiveActionGuidance.BRAKE_AND_SUMMARIZE
    assert snap_88.is_compaction_imminent
    assert "Brake immediately" in snap_88.guidance_message

    # 4. 96% used -> EXHAUSTED / EMERGENCY_HANDOFF
    snap_96 = gauge.inspect(used_tokens=96_000)
    assert snap_96.capacity_pct == 96.0
    assert snap_96.remaining_tokens == 4_000
    assert snap_96.urgency_level == ContextUrgencyLevel.EXHAUSTED
    assert snap_96.suggested_action == CognitiveActionGuidance.EMERGENCY_HANDOFF
    assert snap_96.is_compaction_imminent
    assert "Emergency handoff" in snap_96.guidance_message


def test_remaining_turns_and_dynamic_burn_history() -> None:
    """Verify that recording per-turn burns updates the moving burn rate and turn estimate."""
    config = CognitiveGaugeConfig(
        max_context_tokens=100_000,
        default_turn_token_burn=5_000,
        max_history_turns_tracked=5,
    )
    gauge = ContextCognitiveGauge(config=config)

    # Initially uses default burn rate
    assert gauge.get_average_turn_burn() == 5_000

    # Record 3 turns consuming 1000, 2000, 3000 tokens (avg = 2000)
    gauge.record_turn_burn(1_000)
    gauge.record_turn_burn(2_000)
    gauge.record_turn_burn(3_000)
    assert gauge.get_average_turn_burn() == 2_000

    # Remaining 20,000 tokens with 2,000 avg burn should yield 10 turns
    snap = gauge.inspect(used_tokens=80_000)
    assert snap.estimated_remaining_turns == 10


def test_inspect_from_messages() -> None:
    """Verify token estimation and inspection directly from BaseMessage sequence."""
    gauge = ContextCognitiveGauge()
    messages = [
        SystemMessage(content="You are a senior full-stack AI agent."),
        HumanMessage(content="Please analyze the codebase architecture."),
        AIMessage(content="I have scanned the files and found the entry points."),
    ]
    snapshot = gauge.inspect_from_messages(messages, max_tokens=128_000)

    assert snapshot.total_limit_tokens == 128_000
    assert snapshot.used_tokens > 0
    assert snapshot.remaining_tokens < 128_000
    assert snapshot.capacity_pct < 5.0
    assert snapshot.urgency_level == ContextUrgencyLevel.NOMINAL


def test_create_inspect_context_tool_execution() -> None:
    """Verify that create_inspect_context_tool produces a functional callable BaseTool."""
    config = CognitiveGaugeConfig(max_context_tokens=100_000)
    gauge = ContextCognitiveGauge(config=config)
    tool_en = create_inspect_context_tool(gauge=gauge, locale="en")
    tool_zh = create_inspect_context_tool(gauge=gauge, locale="zh")

    assert tool_en.name == "inspect_context"
    assert "cognitive capacity" in tool_en.description
    assert "油量表" in tool_zh.description

    # Invoke tool with explicit tokens
    raw_output = tool_en.invoke({"current_used_tokens": 50_000})
    parsed = json.loads(raw_output)

    assert parsed["used_tokens"] == 50_000
    assert parsed["capacity_pct"] == 50.0
    assert parsed["urgency_level"] == "nominal"
    assert parsed["suggested_action"] == "EXPLORE_FREELY"
    assert "gauge_rendered_bar" in parsed


@pytest.mark.asyncio
async def test_create_inspect_context_tool_async_execution() -> None:
    """Verify asynchronous tool invocation."""
    tool = create_inspect_context_tool(locale="en")
    raw_output = await tool.ainvoke({"current_used_tokens": 90_000})
    parsed = json.loads(raw_output)

    assert parsed["used_tokens"] == 90_000
    assert parsed["urgency_level"] in ("critical", "converging", "exhausted")


def test_hud_gauge_bar_rendering_bounds() -> None:
    """Verify HUD progress bar rendering across boundary percentages."""
    gauge = ContextCognitiveGauge()

    bar_zero = gauge._render_gauge_bar(0.0, width=10)
    assert bar_zero == "[░░░░░░░░░░] 0.0%"

    bar_half = gauge._render_gauge_bar(50.0, width=10)
    assert bar_half == "[█████░░░░░] 50.0%"

    bar_full = gauge._render_gauge_bar(100.0, width=10)
    assert bar_full == "[██████████] 100.0%"

    bar_over = gauge._render_gauge_bar(150.0, width=10)
    assert bar_over == "[██████████] 100.0%"


def test_multithreaded_burn_recording_thread_safety() -> None:
    """Verify thread safety when recording burns and inspecting concurrently."""
    gauge = ContextCognitiveGauge()

    def worker(token: int) -> None:
        for _ in range(50):
            gauge.record_turn_burn(token)
            snap = gauge.inspect(used_tokens=token * 10)
            assert snap.used_tokens == token * 10

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, 100 + i) for i in range(16)]
        concurrent.futures.wait(futures)

    assert gauge.get_average_turn_burn() > 0
