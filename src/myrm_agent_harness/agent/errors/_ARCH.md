# errors/

## Overview
Agent execution errors with unified diagnostics.

Detailed design: [ERROR_SYSTEM.md](ERROR_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent execution errors with unified diagnostics. | — |
| agent_errors.py | Core | Agent execution errors. ToolStuckException is converted to GraphInterrupt by tool_interceptor_middleware to truly halt agent execution. | ✅ |
| tool_error_category.py | Core | Canonical StrEnum for all tool error categories. Values match frontend i18n keys. | ✅ |
| tool_execution_error.py | Core | Unified tool execution error with structured diagnostics. | ✅ |
| fault_side.py | Core | Deterministic fault-side attribution (MODEL/HARNESS_*/ENV/GRADER/OWNER/UNKNOWN). Pure rules — no LLM calls, no prompt tokens. LLM errors classify via ErrorKind with diagnostic error_type fallback; tool errors classify via ToolErrorCategory. Consumed by stream_executor/event_handlers/agent_runtime error events and trace_builder. | ✅ |

| Submodule | Description |
|-----------|-------------|
| diagnostics/ | Error diagnostics component. Provides LLM error classification, context extraction, and structured d |
