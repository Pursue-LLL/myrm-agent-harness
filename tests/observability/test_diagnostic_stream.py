"""
[INPUT]:
- myrm_agent_harness.observability.diagnostic_stream::*

[OUTPUT]:
- Pytest verification for run-stream diagnostic event separation, dual-track isolation, and severity filtering.

[POS]:
tests/observability/test_diagnostic_stream.py — run-stream 诊断事件分离（与正常消息流解耦）单元测试。
"""

from typing import List
import pytest

from myrm_agent_harness.observability.diagnostic_stream import (
    DiagnosticCategory,
    DiagnosticEvent,
    DiagnosticSeverity,
    DiagnosticStreamDispatcher,
)


def test_dual_track_stream_isolation() -> None:
    dispatcher = DiagnosticStreamDispatcher()
    session_id = "sess_dual_track_001"

    received_messages: List[str] = []
    received_diagnostics: List[DiagnosticEvent] = []

    # 1. 分别订阅正轨消息流与独立诊断通道
    msg_sub_id = dispatcher.subscribe_message(session_id, lambda text: received_messages.append(text))
    diag_sub_id = dispatcher.subscribe_diagnostic(
        session_id, lambda event: received_diagnostics.append(event)
    )

    # 2. 派发正常用户消息
    dispatcher.dispatch_message(session_id, "Hello, ")
    dispatcher.dispatch_message(session_id, "how can I assist you today?")

    # 验证此时诊断通道 100% 为空（绝无普通文本混入）
    assert len(received_messages) == 2
    assert "".join(received_messages) == "Hello, how can I assist you today?"
    assert len(received_diagnostics) == 0

    # 3. 派发一次内部运行时诊断事件（例如：模型触发重试与上下文截断告警）
    diag_event = dispatcher.dispatch_diagnostic(
        session_id=session_id,
        run_id="run_101",
        category=DiagnosticCategory.RETRY,
        severity=DiagnosticSeverity.WARNING,
        code="MODEL_UPSTREAM_429_RETRY",
        message="Upstream provider returned 429; backoff retry 1/3 triggered",
        details={"attempt": "1", "backoff_ms": "500"},
    )

    # 4. 关键验证：正轨消息列表绝对保持 2 条，绝对不增加任何诊断事件！
    assert len(received_messages) == 2
    assert "".join(received_messages) == "Hello, how can I assist you today?"

    # 诊断订阅者精准收到 1 条独立诊断事件
    assert len(received_diagnostics) == 1
    assert received_diagnostics[0].event_id == diag_event.event_id
    assert received_diagnostics[0].category == DiagnosticCategory.RETRY
    assert received_diagnostics[0].severity == DiagnosticSeverity.WARNING
    assert received_diagnostics[0].code == "MODEL_UPSTREAM_429_RETRY"

    # 取消订阅
    dispatcher.unsubscribe(msg_sub_id)
    dispatcher.unsubscribe(diag_sub_id)


def test_diagnostic_severity_filtering_and_stats() -> None:
    dispatcher = DiagnosticStreamDispatcher()
    sess_a = "sess_a"
    sess_b = "sess_b"

    # 派发多条不同等级与领域的诊断事件
    dispatcher.dispatch_diagnostic(
        session_id=sess_a,
        run_id="run_a1",
        category=DiagnosticCategory.CONTEXT_TRUNCATION,
        severity=DiagnosticSeverity.WARNING,
        code="WINDOW_OVERFLOW_PRUNED",
        message="Context pruned 1200 tokens to fit model window",
    )
    dispatcher.dispatch_diagnostic(
        session_id=sess_a,
        run_id="run_a2",
        category=DiagnosticCategory.MCP_LATENCY,
        severity=DiagnosticSeverity.ERROR,
        code="MCP_TIMEOUT",
        message="MCP server github-mcp took 15000ms exceeding threshold",
    )
    dispatcher.dispatch_diagnostic(
        session_id=sess_b,
        run_id="run_b1",
        category=DiagnosticCategory.SANDBOX_PRESSURE,
        severity=DiagnosticSeverity.CRITICAL,
        code="RAM_SPIKE_85_PCT",
        message="Sandbox resident RAM reached 85% safety boundary",
    )

    # 1. 按 session 过滤
    recent_a = dispatcher.get_recent_diagnostics(session_id=sess_a)
    assert len(recent_a) == 2
    assert recent_a[0].category == DiagnosticCategory.MCP_LATENCY  # 最近在前

    # 2. 按 severity 过滤
    criticals = dispatcher.get_recent_diagnostics(severity=DiagnosticSeverity.CRITICAL)
    assert len(criticals) == 1
    assert criticals[0].code == "RAM_SPIKE_85_PCT"

    # 3. 统计汇总
    stats = dispatcher.get_stats()
    assert stats.total_events == 3
    assert stats.by_severity["WARNING"] == 1
    assert stats.by_severity["ERROR"] == 1
    assert stats.by_severity["CRITICAL"] == 1
    assert stats.by_category["CONTEXT_TRUNCATION"] == 1
    assert stats.by_category["MCP_LATENCY"] == 1
    assert stats.by_category["SANDBOX_PRESSURE"] == 1

    # 4. 重置测试
    dispatcher.reset()
    assert len(dispatcher.get_recent_diagnostics()) == 0
    assert dispatcher.get_stats().total_events == 0
