"""Observability module for Myrm Agent Harness

Provides monitoring and health inspection capabilities:
- Prometheus metrics (observability/metrics)
- Auth failure detection (observability/auth_detector)
- Health diagnostics and benchmarks (observability/diagnostics)
- Request tracing context and log correlation (observability/tracing)

[INPUT]
- Exception (POS: LLM call exceptions for auth detection)

[OUTPUT]
- Auth detection functions (detect_auth_failure, get_auth_error_hint)
- Metrics utilities (from observability/metrics)
- Diagnostics (from observability/diagnostics)
- Tracing primitives (TracingContext, TracingLogFilter, JsonFormatter)

[POS]
Observability tools for Myrm Agent framework. Provides passive metric collection,
active health probing, auth failure detection, and request tracing context.
"""

from .auth_detector import detect_auth_failure, get_auth_error_hint
from .tracing import JsonFormatter, TracingContext, TracingLogFilter

__all__ = [
    "JsonFormatter",
    "TracingContext",
    "TracingLogFilter",
    "detect_auth_failure",
    "get_auth_error_hint",
]
