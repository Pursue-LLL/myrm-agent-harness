# observability/

## Overview
Observability tools for Myrm Agent framework. Provides Prometheus metrics, auth failure detection, active health diagnostics, and request tracing context for log correlation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Observability tools — auth detection, tracing primitives re-export. | ✅ |
| auth_detector.py | Core | Authentication failure detection for circuit breaker logic. | ✅ |

| Submodule | Description |
|-----------|-------------|
| metrics/ | Harness-layer generic metrics utilities for any project using the Myrm framework. |
| diagnostics/ | Framework-level self-inspection — health probes, benchmark probes, and diagnostic protocol. |
| tracing/ | ContextVar-based request tracing (trace_id / session_id) with logging.Filter and JSON formatter. |

## Key Dependencies

- `toolkits` (via diagnostics probes)
