"""[INPUT]
- contextlib::{contextmanager}
- typing::{Iterator}
- myrm_agent_harness.observability.tracing.causal.spans::{TraceSpan, SpanKind, SpanStatus, CausalTraceTree}

[OUTPUT]
- CausalTracer: 因果链路跟踪器
- mask_sensitive_payload: 敏感信息脱敏工具函数

[POS]
myrm_agent_harness/observability/tracing/causal/tracer.py — 单次任务因果 TraceSpan 栈管理与脱敏。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from myrm_agent_harness.observability.tracing.causal.spans import (
    CausalTraceTree,
    SpanKind,
    SpanStatus,
    TraceSpan,
)

# 敏感字段键名模式匹配
SENSITIVE_KEY_PATTERN: re.Pattern[str] = re.compile(
    r"(api_?key|token|secret|password|auth|bearer|credential)",
    re.IGNORECASE,
)


def mask_sensitive_payload(key: str, value: str | int | float | bool) -> str | int | float | bool:
    """自动脱敏参数中的密码、令牌与凭据。"""
    if isinstance(value, str) and SENSITIVE_KEY_PATTERN.search(key):
        if len(value) <= 8:
            return "******"
        return f"{value[:3]}***{value[-3:]}"
    return value


class CausalTracer:
    """因果链路追踪器，维护单次请求的因果调用栈。"""

    def __init__(self, trace_id: str | None = None) -> None:
        self.trace_id: str = trace_id or uuid.uuid4().hex
        self._span_stack: list[TraceSpan] = []
        self._root_span: TraceSpan | None = None

    @property
    def current_span(self) -> TraceSpan | None:
        """获取当前活跃的顶层 Span。"""
        return self._span_stack[-1] if self._span_stack else None

    @contextmanager
    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, str | int | float | bool] | None = None,
    ) -> Iterator[TraceSpan]:
        """开启一个因果 Span 上下文，自动建立父子引用关系。"""
        parent = self.current_span
        span = TraceSpan(
            name=name,
            kind=kind,
            trace_id=self.trace_id,
            parent_span_id=parent.span_id if parent else None,
        )

        # 脱敏注入初始属性
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, mask_sensitive_payload(k, v))

        if parent:
            parent.children.append(span)
        elif self._root_span is None:
            self._root_span = span

        self._span_stack.append(span)
        try:
            yield span
            if span.status == SpanStatus.UNSET:
                span.finish(SpanStatus.OK)
        except Exception as exc:
            span.finish(SpanStatus.ERROR, str(exc))
            raise
        finally:
            self._span_stack.pop()

    def get_trace_tree(self) -> CausalTraceTree | None:
        """获取当前构建完成的因果 Trace 树。"""
        if self._root_span is None:
            return None
        return CausalTraceTree(trace_id=self.trace_id, root_span=self._root_span)
