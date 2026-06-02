# errors/

## Overview
Agent execution errors with unified diagnostics.

Detailed design: [ERROR_SYSTEM.md](ERROR_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent execution errors with unified diagnostics. | — |
| agent_errors.py | Core | Agent execution errors. ToolStuckException is converted to GraphInterrupt by tool_interceptor_middleware to truly halt agent execution. | ✅ |
| tool_execution_error.py | Core | Unified tool execution error with structured diagnostics. | ✅ |

| Submodule | Description |
|-----------|-------------|
| diagnostics/ | Error diagnostics component. Provides LLM error classification, context extraction, and structured d |
