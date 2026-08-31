"""Unit tests for Agent Turn Chain Latency Waterfall."""

import pytest

from myrm_agent_harness.observability.latency import (
    LatencyWaterfallAnalyzer,
    TurnChainWaterfall,
    TurnLatencySegment,
    TurnSegmentType,
)


def test_latency_waterfall_analyzer_empty():
    """Test empty segments produce default zero waterfall."""
    waterfall = LatencyWaterfallAnalyzer.build_waterfall(turn_id="turn_empty", segments=[])
    assert waterfall.turn_id == "turn_empty"
    assert waterfall.total_wall_clock_ms == 0.0
    assert waterfall.bottleneck_segment == "NONE"
    assert waterfall.bottleneck_ratio == 0.0


def test_latency_waterfall_sequential_offsets_and_bottleneck():
    """Test sequential offset computation and bottleneck identification."""
    segments = [
        TurnLatencySegment(
            segment_type=TurnSegmentType.LLM_TTFT,
            name="DeepSeek-V3 Prefill",
            duration_ms=450.0,
            tokens=3200,
        ),
        TurnLatencySegment(
            segment_type=TurnSegmentType.LLM_GENERATION,
            name="Stream Output",
            duration_ms=650.0,
            tokens=450,
        ),
        TurnLatencySegment(
            segment_type=TurnSegmentType.TOOL_EXECUTION,
            name="web_fetch",
            duration_ms=1200.0,  # Main bottleneck
        ),
        TurnLatencySegment(
            segment_type=TurnSegmentType.MEMORY_RETRIEVAL,
            name="Qdrant Hybrid Search",
            duration_ms=100.0,
        ),
    ]

    waterfall = LatencyWaterfallAnalyzer.build_waterfall(turn_id="turn_101", segments=segments)

    assert waterfall.turn_id == "turn_101"
    assert waterfall.total_wall_clock_ms == 2400.0
    assert waterfall.total_tool_duration_ms == 1200.0
    assert waterfall.total_llm_duration_ms == 1100.0

    # Segments offset check
    assert waterfall.segments[0].relative_offset_ms == 0.0
    assert waterfall.segments[1].relative_offset_ms == 450.0
    assert waterfall.segments[2].relative_offset_ms == 1100.0
    assert waterfall.segments[3].relative_offset_ms == 2300.0

    # Bottleneck identification
    assert waterfall.bottleneck_segment == "TOOL_EXECUTION:web_fetch"
    assert waterfall.bottleneck_ratio == 0.50  # 1200 / 2400 = 50%

    # Dictionary serialization check
    d = waterfall.to_dict()
    assert d["total_wall_clock_ms"] == 2400.0
    assert d["bottleneck_segment"] == "TOOL_EXECUTION:web_fetch"
    assert len(d["segments"]) == 4
