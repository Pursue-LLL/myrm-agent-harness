"""Unit tests for Context Doctor token breakdown and hotspot analyzer."""

from __future__ import annotations

import pytest
from myrm_agent_harness.agent.event_log._context_doctor import (
    ContextBreakdown,
    ContextHotspot,
    analyze_context_breakdown,
)
from myrm_agent_harness.agent.event_log.trace_types import (
    ExecutionTrace,
    LLMCallRecord,
    ToolCallRecord,
)


def test_analyze_context_breakdown_empty_trace() -> None:
    trace = ExecutionTrace(session_id="s1")
    breakdown = analyze_context_breakdown(trace)

    assert isinstance(breakdown, ContextBreakdown)
    assert breakdown.system_tokens >= 500
    assert breakdown.chat_tokens >= 200
    assert breakdown.tool_tokens == 0
    assert breakdown.file_tokens == 0
    assert breakdown.health_score == 100
    assert breakdown.diagnosis_status == "healthy"
    assert len(breakdown.hotspots) == 0


def test_analyze_context_breakdown_with_tool_hotspots() -> None:
    trace = ExecutionTrace(session_id="s2")

    # Add 2 large tool calls
    trace.tool_calls.append(
        ToolCallRecord(
            sequence=1,
            tool_name="bash_code_execute_tool",
            start_time=100.0,
            end_time=102.0,
            input_data={"command": "pytest -v"},
            output_summary="COMPACTED: bash_code_execute_tool\nCMD: pytest\nEXIT: 0",
            output_data="A" * 16000,  # ~4000 tokens
            success=True,
        )
    )
    trace.tool_calls.append(
        ToolCallRecord(
            sequence=2,
            tool_name="file_read_tool",
            start_time=103.0,
            end_time=104.0,
            input_data={"paths": ["src/main.py"]},
            output_summary=None,
            output_data="def foo():\n    pass\n" * 500,  # file tokens
            success=True,
        )
    )
    trace.llm_calls.append(
        LLMCallRecord(
            sequence=3,
            start_time=105.0,
            end_time=108.0,
            prompt_tokens=12000,
            completion_tokens=500,
            total_tokens=12500,
        )
    )

    breakdown = analyze_context_breakdown(trace)

    assert breakdown.tool_tokens > 0
    assert breakdown.file_tokens > 0
    assert len(breakdown.hotspots) >= 1

    # Verify hotspot fields
    tool_names = [h.tool_name for h in breakdown.hotspots]
    assert "bash_code_execute_tool" in tool_names
    assert "file_read_tool" in tool_names

    bash_hotspot = next(h for h in breakdown.hotspots if h.tool_name == "bash_code_execute_tool")
    assert bash_hotspot.status == "auto_pruned"
    assert bash_hotspot.tokens > 1500

    d = breakdown.to_dict()
    assert "system_tokens" in d
    assert "hotspots" in d
    assert isinstance(d["hotspots"], list)


def test_analyze_context_breakdown_failed_tool_and_critical_status() -> None:
    trace = ExecutionTrace(session_id="s3")

    # Add 1 failed tool call and 1 heavy active tool call
    trace.tool_calls.append(
        ToolCallRecord(
            sequence=1,
            tool_name="web_search",
            start_time=10.0,
            end_time=12.0,
            input_data={"query": "error case"},
            output_summary="Failed to connect",
            output_data=None,
            success=False,
        )
    )
    trace.tool_calls.append(
        ToolCallRecord(
            sequence=2,
            tool_name="heavy_custom_tool",
            start_time=13.0,
            end_time=15.0,
            input_data={"param": "big"},
            output_summary=None,
            output_data="X" * 40000,  # ~10000 tokens
            success=True,
        )
    )
    trace.llm_calls.append(
        LLMCallRecord(
            sequence=3,
            start_time=16.0,
            end_time=18.0,
            prompt_tokens=70000,  # > 64000
            completion_tokens=2000,
            total_tokens=72000,
        )
    )

    breakdown = analyze_context_breakdown(trace)

    assert breakdown.diagnosis_status in ("warning", "critical")
    assert breakdown.health_score < 80
    assert len(breakdown.hotspots) >= 1

    failed_hotspots = [h for h in breakdown.hotspots if h.tool_name == "web_search"]
    assert len(failed_hotspots) == 1
    assert failed_hotspots[0].status == "error"

    heavy_hotspots = [h for h in breakdown.hotspots if h.tool_name == "heavy_custom_tool"]
    assert len(heavy_hotspots) == 1
    assert heavy_hotspots[0].status == "active"
    assert heavy_hotspots[0].tokens > 2000


def test_estimate_payload_tokens_unserializable() -> None:
    from myrm_agent_harness.agent.event_log._context_doctor import _estimate_payload_tokens

    class Unserializable:
        pass

    # Object without json serialization support
    assert _estimate_payload_tokens(Unserializable()) == 0
    assert _estimate_payload_tokens(None) == 0
    assert _estimate_payload_tokens("plain string") > 0


def test_analyze_context_breakdown_tool_dominant_and_heavy_hotspots() -> None:
    trace = ExecutionTrace(session_id="s4")

    # Construct tool calls that dominate context (>70% and >10000 tokens)
    trace.tool_calls.append(
        ToolCallRecord(
            sequence=1,
            tool_name="api_heavy_fetcher",
            start_time=1.0,
            end_time=3.0,
            input_data={"limit": 5000},
            output_summary=None,
            output_data="DATA_RECORD\n" * 12000,  # ~30000 tokens (>8000 tokens hotspot)
            success=True,
        )
    )
    trace.llm_calls.append(
        LLMCallRecord(
            sequence=2,
            start_time=3.0,
            end_time=5.0,
            prompt_tokens=40000,  # > 32000 and <= 64000
            completion_tokens=500,
            total_tokens=40500,
        )
    )

    breakdown = analyze_context_breakdown(trace)

    assert breakdown.tool_tokens > 10000
    assert breakdown.diagnosis_status in ("warning", "critical")
    assert breakdown.health_score <= 70

    # Ensure heavy active hotspot detected
    active_hotspots = [h for h in breakdown.hotspots if h.tokens > 8000 and h.status == "active"]
    assert len(active_hotspots) >= 1


