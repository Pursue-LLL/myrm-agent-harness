# context_pipeline/

## Overview

Request-time context assembly and budget — compression intent, cache feedback,
schema fingerprint, and the ContextPipeline middleware factory.

Detailed design: [MIDDLEWARE_SYSTEM.md](../MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public export for `create_context_pipeline_middleware`. | — |
| `context_pipeline_middleware.py` | Core | `create_context_pipeline_middleware` factory integrating ContextPipeline. | ✅ |
| `context_pipeline_helpers.py` | Internal | Compression intent, cache usage feedback, context budget metadata, schema fingerprint helpers. | ✅ |

## Key Dependencies

- `agent.context_management` — context pipeline processors
- `agent.middlewares.tooling.tool_interceptor_middleware` — LoopGuard accessor
