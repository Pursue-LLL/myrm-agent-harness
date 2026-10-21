"""[INPUT]
- time, uuid, enum, dataclasses
- typing::{Optional, Dict, List, Any}

[OUTPUT]
- SpanKind, SpanStatus: 阶段种类与状态枚举
- TraceSpan: 因果 Span 数据契约
- CausalTraceTree: 完整任务 Trace 树模型

[POS]
myrm_agent_harness/observability/tracing/causal/spans.py — 因果链路 Span 树与 GenAI 语义模型。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class SpanKind(str, Enum):
    """因果链路阶段类型。"""

    INPUT = "input"
    CONTEXT_STAGE = "context_stage"
    LLM_CALL = "llm_call"
    APPROVAL_GATE = "approval_gate"
    TOOL_CALL = "tool_call"
    OUTPUT_DELIVERY = "output_delivery"
    INTERNAL = "internal"


class SpanStatus(str, Enum):
    """Span 运行状态。"""

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"
    DENIED = "denied"
    TIMEOUT = "timeout"


@dataclass
class TraceSpan:
    """因果链路单一执行 Span 节点。"""

    name: str
    kind: SpanKind
    trace_id: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_span_id: str | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    duration_ms: float = 0.0
    status: SpanStatus = SpanStatus.UNSET
    status_message: str = ""
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)
    events: list[dict[str, str | float]] = field(default_factory=list)
    children: list[TraceSpan] = field(default_factory=list)

    def finish(self, status: SpanStatus = SpanStatus.OK, message: str = "") -> None:
        """结束 Span 并结算执行耗时。"""
        self.end_time = time.time()
        self.duration_ms = max(0.0, (self.end_time - self.start_time) * 1000.0)
        self.status = status
        self.status_message = message

    def add_event(self, name: str) -> None:
        """追加时序事件锚点。"""
        self.events.append({"name": name, "timestamp": time.time()})

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        """写入属性键值，自动对敏感字段执行脱敏保护。"""
        import re
        if isinstance(value, str) and re.search(r"(api_?key|token|secret|password|auth|bearer|credential)", key, re.IGNORECASE):
            if len(value) <= 8:
                redacted = "******"
            else:
                redacted = f"{value[:3]}***{value[-3:]}"
            self.attributes[key] = redacted
        else:
            self.attributes[key] = value

    def to_dict(self) -> dict[str, object]:
        """递归导出字典树。"""
        return {
            "name": self.name,
            "kind": self.kind.value,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status.value,
            "status_message": self.status_message,
            "attributes": self.attributes,
            "events": self.events,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class CausalTraceTree:
    """完整请求因果 Trace 链路全景。"""

    trace_id: str
    root_span: TraceSpan
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "root": self.root_span.to_dict(),
        }
