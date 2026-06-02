"""Observability module for Myrm Agent Harness

Provides monitoring and health inspection capabilities:
- Prometheus metrics (observability/metrics)
- Auth failure detection (observability/auth_detector)
- Health diagnostics and benchmarks (observability/diagnostics)

[INPUT]
- Exception (POS: LLM call exceptions for auth detection)

[OUTPUT]
- Auth detection functions (detect_auth_failure, get_auth_error_hint)
- Metrics utilities (from observability/metrics)
- Diagnostics (from observability/diagnostics)

[POS]
Observability tools for Myrm Agent framework. Provides passive metric collection,
active health probing, and auth failure detection.
"""

from .auth_detector import detect_auth_failure, get_auth_error_hint

__all__ = [
    "detect_auth_failure",
    "get_auth_error_hint",
]
