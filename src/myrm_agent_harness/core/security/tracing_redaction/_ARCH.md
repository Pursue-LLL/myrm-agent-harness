# tracing_redaction/

## Overview

Tracing Redaction and Sensitive Data Policy Package.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Tracing Redaction and Sensitive Data Policy Package | ✅ |
| processor.py | Core | Trace processor ensuring redaction policy compliance across lifecycle states — Coordinating telemetry processor that guarantees zero leakage across normal, streaming, error, retry, and resumed agent operations. | ✅ |
| redactor.py | Core | Tracing Sensitive Data Redactor across all execution paths — Harness core security engine for OpenAI-Agents-JS #1970 cross-path tracing redaction consistency. | ✅ |
| sanitizer.py | Core | Sanitizer implementation for telemetry spans under sensitive-data policies — Core sanitization engine ensuring privacy policy consistency across success, error, streaming, retry, and resume spans. | ✅ |
| types.py | Core | Types and schemas for Tracing Redaction and Sensitive Data Policy | ✅ |
