# _internals/

## Overview
Agent internal helpers — private implementation details for agent core files.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent internal helpers — private implementation details for agent core files. | — |
| agent_recovery.py | Core | Agent recovery strategies — context overflow, LLM failover, structured error context. | ✅ |
| agent_runtime.py | Core | Agent runtime — core execution loop (`run_agent_loop`); `apply_bound_skill_catalog_for_stream` / `apply_bound_skill_catalog_for_resume` reinject `<bound_skills>` on SkillAgent streams and resume; both paths sync or remove `skill_search_tool` when bind catalog changes (including empty bind). The run's hook executor is bound again right before the executor task copies the context, so hosts that resume the stream in a fresh task per event (a context hop drops the ContextVars bound in the first step) still get every hook, skill and framework, inside the tool loop. | ✅ |
| base_agent_modes_mixin.py | Core | Deep research + consensus entrypoints mixin for BaseAgent. | ✅ |
| _agent_build.py | Internal | Middleware chain construction, tool registry creation, and tools snapshot emission. | ✅ |
| _agent_helpers.py | Internal | Runtime helper functions — guard reset, query extraction, idle task scheduling, usage ledger init, checkpoint-incompatible merged_context stripping. | ✅ |
| langgraph_guard.py | Core | LangGraph ToolNode monkey-patch for robust tool_call args handling. Uses concurrency-router stage planning to execute mixed batches as ordered parallel stages (instead of all-parallel/all-serial), while preserving mid-batch failure short-circuit semantics. | ✅ |
| memory_extraction.py | Core | Memory auto-extraction utilities. Post-turn LLM compressed-track extraction (always; text-only input — media blocks never reach the prompt and a turn without text is omitted) plus the opt-in verbatim track (`enable_verbatim=True`, default off) with optional LLM-based deep PII scan before persistence. Emits `ExtractionLifecycleObserver` callbacks (extract pending/success/skipped/error; write success/skipped/error only while the verbatim track is enabled; a verbatim failure never aborts the compressed track). | ✅ |
| memory_verbatim.py | Core | Opt-in verbatim track: `create_conversation_memories` chunks messages into ConversationMemory objects; `capture_current_exchange` stores only the newest user/assistant exchange (nothing when the user message carried no text), bypassing the approval queue (content-safety scan still applies). | ✅ |
| run_lifecycle.py | Core | Agent run lifecycle helpers: `setup_workspace` requires `merged_context[\"workspaces_storage_root\"]` and binds aggregate root ContextVar consumed by WorkspaceManager/`WorkspaceService`; `cleanup_run` releases bind tokens; context budget snapshots (incl. checkpoint-derived `turn_count` for GUI preflight, emitted only when checkpoint messages are readable so a stale `0` never masks the frontend fallback) and MESSAGE_END emission (upgrade `completion_status` to `warning` on batch merge failure when LLM status is complete). `post_run_events` accepts an explicit `tracker` (falls back to ContextVar lookup) so `message_end.token_economics` survives async-generator task-boundary resume. | ✅ |

## Key Dependencies

- `observability`
- `toolkits`
- `utils`
