"""Logging filter that injects tracing context into every LogRecord.

Attaches ``trace_id`` and ``session_id`` from ``TracingContext`` so that
any formatter (text or JSON) can reference ``%(trace_id)s`` without the
caller needing to pass extra arguments.

Usage::

    import logging
    from myrm_agent_harness.observability.tracing import TracingLogFilter

    handler = logging.StreamHandler()
    handler.addFilter(TracingLogFilter())
    fmt = logging.Formatter("%(levelname)s [%(trace_id)s] %(message)s")
    handler.setFormatter(fmt)
"""

from __future__ import annotations

import logging

from .context import TracingContext


class TracingLogFilter(logging.Filter):
    """Injects ``trace_id`` and ``session_id`` into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = TracingContext.get_trace_id()  # type: ignore[attr-defined]
        record.session_id = TracingContext.get_session_id()  # type: ignore[attr-defined]
        return True
