# ptc/ — Programmatic Tool Calling

## Overview
Enables LLM-written Python scripts to call agent tools via RPC stubs without consuming LLM context for intermediate results. Dramatically reduces token usage for multi-step batch operations.

## Architecture

```
LLM → bash_code_execute_tool(Python code)
         ↓
    BashExecutor._execute_python_with_ptc()
         ↓
    ptc_injection.inject_ptc_for_python_execution()
         ↓
    PtcRpcServer (asyncio UDS/TCP) started
         ↓
    Child Process ← myrm_tools.py (generated stubs, injected via PYTHONPATH)
        ↓                     ↑
  script runs      ←→   _rpc_call() per tool
        ↓
  stdout/stderr → returned to LLM
```

## File Index

| File | Role | Description |
|------|------|-------------|
| __init__.py | Package | Public API exports |
| _ARCH.md | Doc | This architecture document |
| models.py | Data | Pydantic models: PtcConfig, RPC protocol, execution trace |
| security.py | Security | Env scrubbing, blocked params, safe prefixes |
| helpers.py | Codegen | Built-in helper source (json_parse, shell_quote, retry, path_join) |
| stub_generator.py | Codegen | Generates myrm_tools.py from enabled tool list |
| rpc_server.py | Server | Asyncio UDS/TCP server (one per execution) |
| dispatcher.py | Dispatch | Routes RPC requests to tool.ainvoke(), records trace |
| context.py | Context | PTC nesting guard ContextVar (`ptc_nesting_guard`). | ✅ |
| ptc_injection.py | Orchestrator | Bridges PTC into bash Python path (server lifecycle + env injection) |

## Key Design Decisions

1. **UDS default, TCP fallback** — UDS provides zero-TCP-handshake latency and filesystem-based auth (chmod 600). TCP for Windows only.
2. **Length-prefixed binary protocol** — 4-byte big-endian length prefix + JSON body. Simple, fast, no framing ambiguity.
3. **One connection per call** — Eliminates connection pooling complexity. UDS connect() is ~10μs locally.
4. **Security-first** — Env scrubbing removes all secrets, recursive PTC blocked, terminal params filtered.
5. **Middleware reuse** — Dispatcher calls tool.ainvoke() which flows through tool_interceptor_middleware guards.
6. **Project mode** — When enabled, child process runs in user workspace with venv python, allowing import of project dependencies (pandas, numpy, etc.). Resolves paths at runtime from executor ContextVar.

## Dependencies

- `pydantic` (models)
- `langchain_core.tools` (BaseTool for stub generation and dispatch)
- Standard library: `asyncio`, `socket`, `struct`, `json`, `tempfile`
