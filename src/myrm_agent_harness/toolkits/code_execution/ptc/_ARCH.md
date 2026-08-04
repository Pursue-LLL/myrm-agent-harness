# ptc/ — Workflow RPC（DW PTC 基础设施）

## Overview

**PTC 家族 SSOT**：见 [EXECUTION_SYSTEM.md § PTC 家族](../EXECUTION_SYSTEM.md#ptc-家族programmatic-tool-calling)。

本目录实现 **DW PTC** 分支：RPC 基础设施，供 LLM 编写的 Python 脚本通过 **有界工具集**（`spawn_subagent`、`notify`）调用 Harness 能力，中间结果不进 LLM context。

**MCP PTC**（脚本批量调 MCP）走 bash + `skills.*/tools.*` IPC，**不经过**本目录 RpcServer。两分支同属 PTC，实现路径不同。

## Architecture

```
Dynamic Workflow engine
         ↓
inject_ptc_for_python_execution(ptc_tools=[spawn, notify])
         ↓
PtcRpcServer (asyncio UDS/TCP)
         ↓
Child Process ← myrm_tools.py (generated stubs for allowed tools only)
        ↓                     ↑
  script runs      ←→   _rpc_call() per tool
        ↓
  stdout/stderr → returned to workflow summarizer
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
| context.py | Context | PTC nesting guard ContextVar (`ptc_nesting_guard`); read at inject entry to reject nested sessions. | ✅ |
| ptc_injection.py | Orchestrator | Ephemeral RPC server lifecycle + env injection; fail-closed when RPC start fails (no plain exec fallback). |

## Key Design Decisions

1. **UDS default, TCP fallback** — UDS provides zero-TCP-handshake latency and filesystem-based auth (chmod 600). TCP for Windows only.
2. **Length-prefixed binary protocol** — 4-byte big-endian length prefix + JSON body. Simple, fast, no framing ambiguity.
3. **One connection per call** — Eliminates connection pooling complexity. UDS connect() is ~10μs locally.
4. **Security-first** — Env scrubbing removes all secrets, recursive PTC blocked, terminal params filtered.
5. **Middleware reuse** — Dispatcher calls tool.ainvoke() which flows through tool_interceptor_middleware guards.
6. **Project mode** — When enabled, child process runs in user workspace with venv python, allowing import of project dependencies (pandas, numpy, etc.). Resolves paths at runtime from executor ContextVar.
7. **Prompt contract** — Bash `TOOL_DESCRIPTION` teaches Pure Script + MCP `skills.*/tools.*` batch; single-step work uses native tools. DW orchestration uses inject_ptc with spawn/notify only.

## Dependencies

- `pydantic` (models)
- `langchain_core.tools` (BaseTool for stub generation and dispatch)
- Standard library: `asyncio`, `socket`, `struct`, `json`, `tempfile`
