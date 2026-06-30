# tracing/

## Overview
ContextVar-based request tracing primitives for log correlation. Provides trace_id / session_id propagation, a logging.Filter for automatic injection, and a JSON log formatter. Zero external dependencies — pure Python stdlib.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports TracingContext, TracingLogFilter, JsonFormatter. | ✅ |
| `context.py` | Core | ContextVar storage for trace_id and session_id with token-based reset. | ✅ |
| `log_filter.py` | Core | logging.Filter that reads TracingContext and injects fields into LogRecord. | ✅ |
| `json_formatter.py` | Core | JSON log formatter with tracing fields and automatic secret redaction. | ✅ |

## Key Dependencies

- `core.security.redact` (via json_formatter: redact_sensitive_text)
