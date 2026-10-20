# mcp/

## Overview
MCP Skills — Agent-layer MCP skill transformation.

## `tools.*` builtins routing (SSOT)

| Builtin | Purpose | Turn1 docs | Notes |
|---------|---------|------------|-------|
| `tools.notify` | Python IPC progress → `ptc_notify` SSE | Not appended Turn1; optional in scripts | Rate limit 10 rps; prefer `MYRM_PROGRESS` echo for bash |
| `myrm_tools.notify` | DW orchestration progress | Dynamic Workflow prompt only | Via `inject_ptc`, not regular bash |

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | MCP Skills — Agent-layer MCP skill transformation. | — |
| builtin_registry.py | Core | BuiltinToolRegistry + get_builtin_tool_registry; notify via MCP IPC ``tools.*``. ``get_ptc_description()`` for docs/tests only (not bash Turn1 append). | ✅ |
| builtin_notify.py | Core | PTC builtin handler: `tools.notify` → LangGraph `ptc_notify` custom event for real-time UI updates. Token-bucket rate limited (10rps / burst 20 per session); field validation delegated to `progress_payload.py`. | ✅ |
| progress_payload.py | Core | Shared notify/progress field SSOT (`parse_ptc_notify_params`, `build_workflow_stage_event`, `build_ptc_notify_payload`). Used by PTC `notify_handler` and DW `NotifyProgressTool`. | ✅ |
| notify_registry.py | Core | Session→RunnableConfig registry (with `session_scope` async ctx mgr) so the IPC task can resolve the caller's config for `notify` dispatch. | ✅ |
| client_templates.py | Core | Provides MCPError, generate_ipc_client_code. Injects `_SESSION_ID` / `_WORKSPACE_ROOT` / `_AUTH_TOKEN` / `_TRACE_NONCE` into the in-script IPC client. Emits call markers as `__MCP_DATA__{nonce}{base64(json)}__END__{nonce}`, omitted entirely when no nonce is available. | ✅ |
| core_generator.py | Core | MCP Skill Generator — MCP-to-Skill conversion with progressive disclosure. Connects to all MCP servers in parallel (`asyncio.gather`), serializes configs via `mcp_config_to_runtime_dict` SSOT, and reads tools + instructions from warm pooled connections (`conn.tools_by_server` / `conn.instructions_by_server`), reusing the same persistent sessions at runtime. | ✅ |
| executor.py | Core | Provides SkillExecutionContext, SkillExecutor. Resolves MCP skills via `skill_registry.get_mcp_skill_for_ipc` and propagates `session_id` / `workspace_root` to the generated client code. | ✅ |
| ipc_proxy.py | Core | Provides MCPIPCRequest/Response/Server, `IPCCallContext` + `get_ipc_call_context` (ContextVar) so builtin handlers can read per-call session metadata. Mints `auth_token` (bearer, checked constant-time) and `trace_nonce` (marker authentication); `get_mcp_trace_nonce()` fails closed once the server stops. Enforces runtime path policy (`check_path_policy`), agent MCP scope gate (`verify_tool_invocation`), and read-only policy. Transport is AF_UNIX on POSIX and loopback TCP (`tcp_port`) where asyncio cannot open AF_UNIX streams, mirroring the DW track's fallback. | ✅ |
| tool_name_utils.py | Core | resolve_mcp_tool_name — canonical MCP tool name matching (_/- aliases, server prefix strip). | ✅ |
| schema_doc_utils.py | Core | JSON Schema constraint extraction and markdown rendering for MCP tool documentation (params section, call examples). | ✅ |
| proxy_service.py | Core | MCPSkillProxyService with warm-pool invoke, `skill_registry.get_mcp_skill_for_ipc` lookup, full `MCPConfig` + `_injected_auth_headers` restoration, required-arg probe validation, read-only session cache (only tools declaring `readOnlyHint`, keyed by session, 60s TTL; mutating tools never cached), and `parse_mcp_result` (unwrap security envelope + JSON parse for PTC consumers). | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `utils`
