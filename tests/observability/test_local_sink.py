"""
[INPUT]:
- myrm_agent_harness.observability.local_sink::LocalDiskTelemetrySink, LocalSpanRecord

[OUTPUT]:
- Pytest verification for Opt-In disk persistence, ring buffer retrieval, metrics logging, and failure isolation.

[POS]:
tests/observability/test_local_sink.py — OpenTelemetry 缺失降级与本地盘兜底单元测试。
"""

import json
from pathlib import Path
import tempfile

import pytest

from myrm_agent_harness.observability.local_sink import (
    LocalDiskTelemetrySink,
    LocalSpanRecord,
)


def test_local_sink_opt_in_persistence_and_ring_buffer() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        disk_file = Path(tmpdir) / "test_spans.jsonl"
        sink = LocalDiskTelemetrySink(enabled=True, storage_path=str(disk_file))

        assert sink.is_enabled is True

        # 记录 3 条 Spans
        span_1 = sink.record_span(
            trace_id="tr_001",
            span_id="sp_001",
            name="tool_execution:web_search",
            duration_ms=124.56,
            status="OK",
            attributes={"tool": "web_search", "query": "python 3.13"},
        )
        assert span_1.name == "tool_execution:web_search"
        assert span_1.duration_ms == 124.56

        sink.record_span(
            trace_id="tr_001",
            span_id="sp_002",
            name="llm_inference:claude-3-7-sonnet",
            duration_ms=850.12,
            status="OK",
            attributes={"model": "claude-3-7-sonnet"},
        )

        sink.record_span(
            trace_id="tr_001",
            span_id="sp_003",
            name="prompt_cache_lookup",
            duration_ms=12.0,
            status="HIT",
            attributes={"cache_type": "ephemeral"},
        )

        # 验证环形缓冲区
        recent = sink.get_recent_spans(limit=2)
        assert len(recent) == 2
        assert recent[-1].name == "prompt_cache_lookup"

        # 验证磁盘持久化文件内容
        assert disk_file.exists()
        lines = disk_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

        parsed_last = json.loads(lines[-1])
        assert parsed_last["span_id"] == "sp_003"
        assert parsed_last["status"] == "HIT"

        # 验证状态
        status = sink.get_status()
        assert status.is_enabled is True
        assert status.persisted_spans_count == 3
        assert status.buffered_spans_count == 3
        assert status.file_size_bytes > 0


def test_local_sink_disabled_mode_and_failure_isolation() -> None:
    # 场景 1: 未开启本地盘时，仅在内存缓冲，不写磁盘
    with tempfile.TemporaryDirectory() as tmpdir:
        disk_file = Path(tmpdir) / "disabled_spans.jsonl"
        sink = LocalDiskTelemetrySink(enabled=False, storage_path=str(disk_file))

        sink.record_span(
            trace_id="tr_002",
            span_id="sp_010",
            name="noop_test",
            duration_ms=5.0,
        )

        assert not disk_file.exists()
        status = sink.get_status()
        assert status.is_enabled is False
        assert status.persisted_spans_count == 0
        assert status.buffered_spans_count == 1

    # 场景 2: 存储路径发生底层异常（不可写路径），安全吞异常绝不抛出崩溃
    bad_sink = LocalDiskTelemetrySink(enabled=True, storage_path="/dev/null/illegal/path/test.jsonl")
    # record_span 绝不抛异常
    span = bad_sink.record_span(
        trace_id="tr_003",
        span_id="sp_020",
        name="isolated_span",
        duration_ms=10.0,
    )
    assert span.span_id == "sp_020"
