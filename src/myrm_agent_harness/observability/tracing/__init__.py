"""Request tracing context for log correlation.

Provides ContextVar-based trace propagation and a logging.Filter
that automatically injects ``trace_id`` / ``session_id`` into every
LogRecord. Designed for cloud-hosted observability (Loki, ELK) while
adding negligible overhead to local deployments.

[INPUT]
- (none — pure stdlib utilities)

[OUTPUT]
- TracingContext: ContextVar accessors for trace_id / session_id
- TracingLogFilter: logging.Filter that enriches LogRecord
- JsonFormatter: JSON log formatter with tracing fields

[POS]
Harness-layer tracing primitives, parallel to ``observability/metrics/``.
Zero external dependencies — uses only Python stdlib (contextvars, logging, json).
"""

from .context import TracingContext
from .json_formatter import JsonFormatter
from .log_filter import TracingLogFilter

__all__ = [
    "JsonFormatter",
    "TracingContext",
    "TracingLogFilter",
]
