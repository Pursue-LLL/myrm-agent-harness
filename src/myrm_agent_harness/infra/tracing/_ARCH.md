# tracing/

## Overview
Distributed tracing and metrics collection. Integrates OpenTelemetry for call chain tracing, performance analysis, and metrics export.

Detailed design: [TRACE_STORAGE_SYSTEM.md](TRACE_STORAGE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Distributed tracing and metrics collection. Integrates OpenTelemetry for call chain tracing, perform | ✅ |
| propagation.py | Core | Trace context propagation. Maintains complete trace chains across service calls. | ✅ |
| sampling.py | Core | Intelligent sampling strategy. 100% for errors, 100% for slow requests, 100% for critical paths, 10% | ✅ |
| tracer.py | Core | Tracer utilities. Provides OpenTelemetry span creation and tracing decorators. | ✅ |

| Submodule | Description |
|-----------|-------------|
| metrics/ | Metrics export module. Supports Prometheus, OTLP, Console, and other exporters. |

## Optional install

- **`[observability]` extra**: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `openinference-instrumentation-langchain`
- `opentelemetry-api` is a core dependency; SDK and exporters are optional
- `opentelemetry-instrumentation` is installed transitively via `openinference-instrumentation-langchain`
