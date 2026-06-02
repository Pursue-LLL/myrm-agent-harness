# observability/

## Overview
Observability tools for Myrm Agent framework. Provides Prometheus metrics, auth failure detection, circuit breaker utilities, and active health diagnostics for monitoring system health.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Observability tools — auth failure detection and metrics re-export. | ✅ |
| auth_detector.py | Core | Authentication failure detection for circuit breaker logic. | ✅ |

| Submodule | Description |
|-----------|-------------|
| metrics/ | Harness-layer generic metrics utilities for any project using the Myrm framework. |
| diagnostics/ | Framework-level self-inspection — health probes, benchmark probes, and diagnostic protocol. |

## Key Dependencies

- `toolkits` (via diagnostics probes)
