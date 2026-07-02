# mcp/

## Overview
MCP Skills — Agent-layer MCP skill transformation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | MCP Skills — Agent-layer MCP skill transformation. | — |
| builtin_registry.py | Core | Provides BuiltinToolEntry, BuiltinToolRegistry, get_builtin_tool_registry. Registers PTC-only builtins (session_store/load/keys, notify). Web uses native tools + PTC RPC stubs. | ✅ |
| builtin_session_store.py | Core | PTC builtin handlers: cross-call file-backed session KV store at `<workspace>/.session_store/<sid>.json` (session_id is sanitised via `_SAFE_SESSION_ID_RE` to prevent path traversal). | ✅ |
| builtin_notify.py | Core | PTC builtin handler: `tools.notify` → LangGraph `ptc_notify` custom event for real-time UI updates. Token-bucket rate limited (10rps / burst 20 per session); supports structured fields `progress` / `step_index` / `total_steps` / `category` for inline ActivityCard grouping. | ✅ |
| notify_registry.py | Core | Session→RunnableConfig registry (with `session_scope` async ctx mgr) so the IPC task can resolve the caller's config for `notify` dispatch. | ✅ |
| client_templates.py | Core | Provides MCPError, generate_ipc_client_code. Injects `_SESSION_ID` / `_WORKSPACE_ROOT` into the in-script IPC client. | ✅ |
| core_generator.py | Core | MCP Skill Generator — MCP-to-Skill conversion with progressive disclosure. Reads tools + instructions from a warm pooled connection (`conn.tools_by_server` / `conn.instructions_by_server`), reusing the same persistent session at runtime (no separate enumeration spawn). | ✅ |
| executor.py | Core | Provides SkillExecutionContext, SkillExecutor. Propagates `session_id` / `workspace_root` to the generated client code. | ✅ |
| ipc_proxy.py | Core | Provides MCPIPCRequest/Response/Server, `IPCCallContext` + `get_ipc_call_context` (ContextVar) so builtin handlers can read per-call session metadata. | ✅ |
| proxy_service.py | Core | Provides MCPSkillProxyService, MCPInvokeResult, get_mcp_skill_proxy_service. Routes live PTC/IPC tool calls through the warm connection pool (`conn.call`) so invocations reuse the persistent session instead of re-spawning per call. | ✅ |
| schema_doc_utils.py | Core | JSON Schema constraint extraction and markdown rendering for MCP tool documentation (params section, call examples). | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `utils`
