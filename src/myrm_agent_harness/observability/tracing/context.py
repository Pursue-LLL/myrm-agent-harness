"""ContextVar-based request tracing context.

Stores ``trace_id`` and ``session_id`` as context-local variables so that
any code running in the same async task (or thread) can read the current
trace identity without explicit parameter passing.

Usage::

    TracingContext.set_trace_id("abc-123")
    print(TracingContext.get_trace_id())  # "abc-123"

    # Or use the token-based reset pattern
    token = TracingContext.set_trace_id("def-456")
    # ... do work ...
    TracingContext.reset_trace_id(token)
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
