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
| core_generator.py | Core | MCP Skill Generator — orchestration for MCP-to-Skill conversion. Connects to all MCP servers in parallel (`asyncio.gather`), serializes configs via `mcp_config_to_runtime_dict` SSOT, reads tools + instructions from warm pooled connections, assembles L2 from `doc_rendering`, resolves L1 descriptions via `description`, and generates L3 tool docs. Colliding server names are disambiguated (`_2`) so no server is dropped; L1 descriptions are scanned for high-risk findings. | ✅ |
| doc_rendering.py | Core | Pure L2 rendering layer: `L2_MAX_TOKENS` (3,000), instructions cap (2,000), measured fixed cost (224), tier-note reserve (96), tool-section budget with a 680 floor, `full → required → names` degradation chosen by token budget (not tool count), `cap_instructions`, and shared text helpers (`truncate_to_sentence` / `clean_markdown` / `text_field`). `build_tool_section` requires an explicit budget so no caller can silently ignore instructions. | ✅ |
| description.py | Core | Pure L1 description policy: `resolve_description` (user description > instructions first sentence > tool summary) and `build_description_from_tools` (up to three tool descriptions, `and N more` suffix). | ✅ |
| executor.py | Core | Provides SkillExecutionContext, SkillExecutor. Resolves MCP skills via `skill_registry.get_mcp_skill_for_ipc` and propagates `session_id` / `workspace_root` to the generated client code. | ✅ |
| ipc_proxy.py | Core | Provides MCPIPCRequest/Response/Server, `IPCCallContext` + `get_ipc_call_context` (ContextVar) so builtin handlers can read per-call session metadata. Mints `auth_token` (bearer, checked constant-time) and `trace_nonce` (marker authentication); `get_mcp_trace_nonce()` fails closed once the server stops. Enforces runtime path policy (`check_path_policy`), agent MCP scope gate (`verify_tool_invocation`), and read-only policy. Transport is AF_UNIX on POSIX and loopback TCP (`tcp_port`) where asyncio cannot open AF_UNIX streams, mirroring the DW track's fallback. | ✅ |
| tool_name_utils.py | Core | Single source of truth for MCP tool-name matching: `parse_mcp_tool_name` prefix parsing, `to_python_identifier` (dots/spaces/leading digits → valid Python), `build_tool_name_map` (deterministic `_2` collision suffixes), and `resolve_mcp_tool_name` (Python name → canonical). Shared by L2 rendering, L3 doc paths, proxy invocation, and reload summaries. | ✅ |
| schema_doc_utils.py | Core | JSON Schema constraint extraction and markdown rendering for MCP tool documentation (params section, call examples, response notes), plus the compact signature renderers (`render_signature` / `render_type` / `render_constraint`): one line per tool with required-first params, `?` optional markers, and short enum/regex hints. Dot-path (flattened) parameters render their call example as a `**{...}` dict splat so the sample stays valid Python. Rendering policy and budgets live in `doc_rendering`. | ✅ |
| proxy_service.py | Core | MCPSkillProxyService with warm-pool invoke, `skill_registry.get_mcp_skill_for_ipc` lookup, full `MCPConfig` + `_injected_auth_headers` restoration, required-arg probe validation, read-only session cache (only tools declaring `readOnlyHint`, keyed by session, 60s TTL; mutating tools never cached), and `parse_mcp_result` (unwrap security envelope + JSON parse for PTC consumers). | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `utils`
