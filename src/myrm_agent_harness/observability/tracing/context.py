"""ContextVar-based request tracing context.

[INPUT]
- None (standard library contextvars & uuid)
- myrm_agent_harness.infra.tracing.propagation (optional runtime OpenTelemetry span resolution)

[OUTPUT]
- TracingContext: accessor over contextvars for request-scoped trace_id and session_id
- resolve_current_trace_id: hierarchical active trace resolution across OTel and ContextVar

[POS]
Low-level tracing context store and trace ID resolution helper for distributed observability.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_UNSET = "-"

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default=_UNSET)
_session_id_var: ContextVar[str] = ContextVar("session_id", default=_UNSET)


class TracingContext:
    """Thin accessor over ``contextvars`` for request-scoped tracing IDs."""

    __slots__ = ()

    @staticmethod
    def get_trace_id() -> str:
        return _trace_id_var.get()

    @staticmethod
    def set_trace_id(value: str) -> Token[str]:
        return _trace_id_var.set(value)

    @staticmethod
    def reset_trace_id(token: Token[str]) -> None:
        _trace_id_var.reset(token)

    @staticmethod
    def get_session_id() -> str:
        return _session_id_var.get()

    @staticmethod
    def set_session_id(value: str) -> Token[str]:
        return _session_id_var.set(value)

    @staticmethod
    def reset_session_id(token: Token[str]) -> None:
        _session_id_var.reset(token)

    @staticmethod
    def generate_trace_id() -> str:
        """Generate a compact 32-char hex trace ID (UUID4 without dashes)."""
        return uuid.uuid4().hex


def resolve_current_trace_id() -> str | None:
    """Resolve active trace ID across OpenTelemetry, ContextVar TracingContext, or None.

    Hierarchy:
    1. Active OpenTelemetry Span trace_id (valid 32-hex string)
    2. ContextVar TracingContext.get_trace_id() (if set and not unset '-')
    3. None
    """
    try:
        from myrm_agent_harness.infra.tracing.propagation import get_current_trace_id

        otel_trace = get_current_trace_id()
        if otel_trace and otel_trace != "0" * 32:
            return otel_trace
    except Exception:
        pass

    ctx_trace = TracingContext.get_trace_id()
    if ctx_trace and ctx_trace != _UNSET:
        return ctx_trace

    return None

