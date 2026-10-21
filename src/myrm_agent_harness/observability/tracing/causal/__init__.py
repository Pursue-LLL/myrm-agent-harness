"""[INPUT]
- .spans::{CausalTraceTree, SpanKind, SpanStatus, TraceSpan}
- .tracer::{CausalTracer, mask_sensitive_payload}
- .otel_bridge::{ZeroDepOTelBridge}

[OUTPUT]
- 导出因果链路追踪与无依赖 OTel 遥测降级桥

[POS]
myrm_agent_harness/observability/tracing/causal/__init__.py — 因果追踪模块入口门面。
"""

from __future__ import annotations

from .otel_bridge import ZeroDepOTelBridge
from .spans import CausalTraceTree, SpanKind, SpanStatus, TraceSpan
from .tracer import CausalTracer, mask_sensitive_payload

__all__ = [
    "CausalTraceTree",
    "CausalTracer",
    "SpanKind",
    "SpanStatus",
    "TraceSpan",
    "ZeroDepOTelBridge",
    "mask_sensitive_payload",
]
