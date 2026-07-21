# _internals/

## Overview
Agent internal helpers — private implementation details for agent core files.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent internal helpers — private implementation details for agent core files. | — |
| agent_recovery.py | Core | Agent recovery strategies — context overflow, LLM failover, structured error context. | ✅ |
| agent_runtime.py | Core | Agent runtime — core execution loop (`run_agent_loop`). Delegates build logic to `_agent_build` and helpers to `_agent_helpers`. | ✅ |
| _agent_build.py | Internal | Middleware chain construction, tool registry creation, and tools snapshot emission. | ✅ |
| _agent_helpers.py | Internal | Runtime helper functions — guard reset, query extraction, idle task scheduling, usage ledger init. | ✅ |
| langgraph_guard.py | Core | LangGraph ToolNode monkey-patch for robust tool_call args handling. Uses concurrency-router stage planning to execute mixed batches as ordered parallel stages (instead of all-parallel/all-serial), while preserving mid-batch failure short-circuit semantics. | ✅ |
| memory_extraction.py | Core | Memory auto-extraction utilities. Dual-track extraction (verbatim + compressed) with optional LLM-based deep PII scan before persistence. | ✅ |
| run_lifecycle.py | Core | Agent run lifecycle helpers: `setup_workspace` requires `merged_context[\"workspaces_storage_root\"]` and binds aggregate root ContextVar consumed by WorkspaceManager/`WorkspaceService`; `cleanup_run` releases bind tokens; context budget snapshots and MESSAGE_END emission. | ✅ |

## Key Dependencies

- `observability`
- `toolkits`
- `utils`
