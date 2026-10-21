"""[INPUT]
- tmp_path, json
- myrm_agent_harness.observability.tracing.causal::{CausalTracer, SpanKind, SpanStatus, ZeroDepOTelBridge, mask_sensitive_payload}

[OUTPUT]
- Pytest test cases verifying causal span nesting, error handling, secret redaction, and telemetry export.

[POS]
tests/observability/tracing/test_causal_tracing.py — 因果 TraceSpan 树与遥测桥接单元测试。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.observability.tracing.causal import (
    CausalTracer,
    SpanKind,
    SpanStatus,
    ZeroDepOTelBridge,
    mask_sensitive_payload,
)


def test_mask_sensitive_payload() -> None:
    # 验证敏感字段脱敏
    assert mask_sensitive_payload("api_key", "sk-1234567890abcdef") == "sk-***def"
    assert mask_sensitive_payload("user_token", "short") == "******"
    assert mask_sensitive_payload("password", "p@ssw0rd123") == "p@s***123"

    # 非敏感字段保持不变
    assert mask_sensitive_payload("model_name", "deepseek-r1") == "deepseek-r1"
    assert mask_sensitive_payload("count", 42) == 42


def test_causal_tracer_hierarchical_span_tree() -> None:
    tracer = CausalTracer(trace_id="test-trace-123")

    with tracer.start_span("agent_turn", kind=SpanKind.INPUT) as root:
        root.set_attribute("user_query", "Explain quantum physics")

        with tracer.start_span("context_stage", kind=SpanKind.CONTEXT_STAGE) as ctx_span:
            ctx_span.set_attribute("pruned_tokens", 150)

        with tracer.start_span("llm_call", kind=SpanKind.LLM_CALL) as llm_span:
            llm_span.set_attribute("model", "deepseek-r1")
            llm_span.set_attribute("api_key", "sk-secret-key-999")

            with tracer.start_span("tool_call", kind=SpanKind.TOOL_CALL) as tool_span:
                tool_span.set_attribute("tool_name", "web_search")

        with tracer.start_span("output_delivery", kind=SpanKind.OUTPUT_DELIVERY) as out_span:
            out_span.set_attribute("channel", "sse_stream")

    tree = tracer.get_trace_tree()
    assert tree is not None
    assert tree.trace_id == "test-trace-123"

    root_dict = tree.root_span.to_dict()
    assert root_dict["name"] == "agent_turn"
    assert root_dict["status"] == "ok"
    assert root_dict["duration_ms"] >= 0.0

    children = root_dict["children"]
    assert len(children) == 3  # context_stage, llm_call, output_delivery
    assert children[0]["name"] == "context_stage"
    assert children[1]["name"] == "llm_call"
    assert children[2]["name"] == "output_delivery"

    # 验证 llm_call 的子 span (tool_call)
    llm_children = children[1]["children"]
    assert len(llm_children) == 1
    assert llm_children[0]["name"] == "tool_call"

    # 验证敏感属性已脱敏
    assert children[1]["attributes"]["api_key"] == "sk-***999"


def test_causal_tracer_handles_exception_and_marks_error() -> None:
    tracer = CausalTracer()

    with pytest.raises(ValueError, match="simulated failure"):
        with tracer.start_span("failing_task", kind=SpanKind.INTERNAL):
            with tracer.start_span("sub_operation", kind=SpanKind.TOOL_CALL):
                raise ValueError("simulated failure")

    tree = tracer.get_trace_tree()
    assert tree is not None
    root_dict = tree.root_span.to_dict()
    assert root_dict["status"] == "error"
    assert "simulated failure" in root_dict["status_message"]

    sub_dict = root_dict["children"][0]
    assert sub_dict["status"] == "error"
    assert "simulated failure" in sub_dict["status_message"]


def test_zero_dep_otel_bridge_export_and_file_dump(tmp_path: Path) -> None:
    tracer = CausalTracer(trace_id="trace-export-456")
    with tracer.start_span("root_job", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("job_type", "batch_eval")

    tree = tracer.get_trace_tree()
    assert tree is not None

    bridge = ZeroDepOTelBridge(output_dir=tmp_path)
    exported = bridge.export_trace_tree(tree)

    assert exported["trace_id"] == "trace-export-456"
    assert exported["root"]["name"] == "root_job"

    # 验证写入了本地 JSON 文件
    file_path = tmp_path / "trace_trace-export-456.json"
    assert file_path.exists()

    content = json.loads(file_path.read_text(encoding="utf-8"))
    assert content["trace_id"] == "trace-export-456"
