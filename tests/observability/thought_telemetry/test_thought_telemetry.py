"""[INPUT]
- myrm_agent_harness.observability.thought_telemetry::{
    CoTRunawayGuard,
    RunawayReason,
    ThoughtTelemetryTracker,
}

[OUTPUT]
- test_thought_tracker_step_detection_and_metrics
- test_runaway_guard_ngram_loop_detection
- test_runaway_guard_excessive_length
- test_tracker_clean_run_no_runaway

[POS]
tests/observability/thought_telemetry/test_thought_telemetry.py — 思维流实时遥测与死循环失控熔断单元测试。
"""

from __future__ import annotations

import time

from myrm_agent_harness.observability.thought_telemetry import (
    CoTRunawayGuard,
    RunawayReason,
    ThoughtTelemetryTracker,
)


def test_thought_tracker_step_detection_and_metrics() -> None:
    """流式接收 chunk 时，应准确识别推演步骤标记并累加耗时与 Token 数。"""
    tracker = ThoughtTelemetryTracker()

    chunk1 = "首先分析用户需求。我们需要设计一个分布式诊断探针。\n"
    s1 = tracker.append_chunk(chunk1)
    assert s1.step_count >= 1
    assert s1.token_count > 0
    assert s1.elapsed_ms >= 0.0

    chunk2 = "重新考虑：等等，这里的超时阈值可能需要调整。\n"
    s2 = tracker.append_chunk(chunk2)
    assert s2.step_count >= 2

    chunk3 = "\nStep 3: 开始组装最终结论与行动方案。"
    s3 = tracker.append_chunk(chunk3)
    assert s3.step_count >= 3
    assert s3.is_runaway_detected is False


def test_runaway_guard_ngram_loop_detection() -> None:
    """当思维链陷入高频循环复读时，CoTRunawayGuard 应精准报警并给出软中断指引。"""
    guard = CoTRunawayGuard(min_chars_for_analysis=100, repetition_threshold=0.40)
    tracker = ThoughtTelemetryTracker(guard=guard)

    # 模拟长文本背景
    base_text = "我们在评估算法的收敛性。这需要深入分析每一个分支。\n" * 5
    tracker.append_chunk(base_text)

    # 注入严重死循环复读片段
    loop_sentence = "wait let me check the equation once more and reconsider the branch "
    loop_text = loop_sentence * 8

    snapshot = tracker.append_chunk(loop_text)
    assert snapshot.is_runaway_detected is True
    assert snapshot.runaway_reason == RunawayReason.NGRAM_REPETITION_LOOP
    assert snapshot.soft_interrupt_hint is not None
    assert "死循环" in snapshot.soft_interrupt_hint or "停止" in snapshot.soft_interrupt_hint


def test_runaway_guard_excessive_length() -> None:
    """当思考消耗 Token 超过安全预算上限时，应触发 EXCESSIVE_LENGTH 熔断。"""
    guard = CoTRunawayGuard(max_budget_tokens=2000)
    tracker = ThoughtTelemetryTracker(guard=guard)

    # 显式传入超过 2000 tokens
    snapshot = tracker.append_chunk("思考中...", exact_tokens=2500)
    assert snapshot.is_runaway_detected is True
    assert snapshot.runaway_reason == RunawayReason.EXCESSIVE_LENGTH
    assert "预算上限" in str(snapshot.soft_interrupt_hint)


def test_tracker_clean_run_no_runaway() -> None:
    """正常健康的思考链不应误报死循环，发散度应保持在健康范围。"""
    tracker = ThoughtTelemetryTracker()
    chunks = [
        "从第一性原理出发分析系统瓶颈。",
        "网络层可能存在抖动，但 TCP 握手正常。",
        "检查服务端进程发现守护进程正常运行。",
        "因此结论是 Provider 余额可能存在问题。",
    ]

    snapshot = None
    for c in chunks:
        snapshot = tracker.append_chunk(c + "\n")

    assert snapshot is not None
    assert snapshot.is_runaway_detected is False
    assert snapshot.runaway_reason == RunawayReason.NONE
    assert snapshot.divergence_score < 0.9
