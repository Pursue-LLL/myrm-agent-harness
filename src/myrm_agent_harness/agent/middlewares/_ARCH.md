# middlewares/

## Overview

Agent middleware system exports. Provides the complete middleware stack (context management, debug logging, tool interception, filesystem search).

Detailed design: [MIDDLEWARE_SYSTEM.md](MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public middleware exports. | ✅ |
| `_session_context.py` | Internal | Shared ContextVars for the middleware chain. | ✅ |
| `clarification_guard_middleware.py` | Core | Enforces single `ask_question_tool` call per turn; blocks coexisting tool calls with synthetic errors. | ✅ |
| `debug_logger_middleware.py` | Core | Full message list debug logging. | ✅ |
| `filesystem_search_middleware.py` | Core | Inject glob/grep workspace search tools. | ✅ |
| `plan_confirm_middleware.py` | Core | Plan-phase HITL: intercept first `todo_write(merge=False)` with 3+ items for user review via `interrupt()`. | ✅ |
| `progress_middleware.py` | Core | Active todo focus injection into last HumanMessage. | ✅ |
| `goal_focus_middleware.py` | Core | ACTIVE goal objective injection into last HumanMessage. | ✅ |
| `moa_advisor_middleware.py` | Core | Agent-loop MoA advisor overlay — ref fan-out, transient HumanMessage tail, skip SSE for budget pressure and insufficient refs (`moa_overlay_skipped`). | ✅ |
| `rate_limit.py` | Core | Proactive provider 429 throttling. | ✅ |
| `replan_middleware.py` | Core | Dynamic replan loop on tool errors. | ✅ |
| `security_boundary_middleware.py` | Core | Security boundary enforcement. | ✅ |
| `security_guardrail_middleware.py` | Core | Security guardrail enforcement. | ✅ |
| `session_access_middleware.py` | Core | Inject per-turn HITL session directory access context (`<session-access>` block) before each model call; dedup via marker. | ✅ |
| `subagent_limit_middleware.py` | Core | Max concurrent subagents per turn. | ✅ |
| `sync_hook_parity.py` | Internal | `SyncHookParityAdapter` wraps middlewares missing sync `wrap_tool_call`/`wrap_model_call` so sync ToolNode paths don't raise; `apply_sync_hook_parity()` auto-wraps the middleware list. | ✅ |

| Submodule | Description |
|-----------|-------------|
| `completion/` | Finish gate, verification checklist, external evidence, deliverable write checks. See [completion/_ARCH.md](completion/_ARCH.md). |
| `approval/` | HITL approval queue, batch, scheduler. See [approval/_ARCH.md](approval/_ARCH.md). |
| `approval_interception/` | Approval interception recognizer. See [approval_interception/_ARCH.md](approval_interception/_ARCH.md). |
| `guardrails/` | Guardrail provider chain + GuardrailMiddleware. See [guardrails/_ARCH.md](guardrails/_ARCH.md). |
| `tooling/` | Single interception point for all tool calls: interceptor, executor, history hygiene, dangling-call repair, skill attenuation, and their guards/helpers. See [tooling/_ARCH.md](tooling/_ARCH.md). |
| `context_pipeline/` | Request-time context assembly and budget (compression intent, cache feedback, schema fingerprint). See [context_pipeline/_ARCH.md](context_pipeline/_ARCH.md). |
| `memory_context/` | User memory injection into model calls (`<user_memory_context>`, scope boundary, untrusted wrapping, telemetry). See [memory_context/_ARCH.md](memory_context/_ARCH.md). |
| `concurrency/` | Subagent semaphore limits, safe tool dispatch, parallel tool batch routing. See [concurrency/_ARCH.md](concurrency/_ARCH.md). |
| `security/` | Security enforcement middleware: boundary rules injection + eight-layer guardrail defense. See [security/_ARCH.md](security/_ARCH.md). |

## Key Dependencies

- `agent/context_management/` — context pipeline processors
- `agent/security/` — tool result validation, guards
- `infra`
- `observability`
- `toolkits`
- `utils`
