# middlewares/

## Overview

Agent middleware system exports. Provides the complete middleware stack (context management, debug logging, tool interception, filesystem search).

Detailed design: [MIDDLEWARE_SYSTEM.md](MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public middleware exports. | ✅ |
| `_session_context.py` | Internal | Shared ContextVars for the middleware chain. | ✅ |
| `_mutation_verifier.py` | Internal | Per-turn file mutation verifier → SSE on failure. | ✅ |
| `_skill_failure_tracking.py` | Internal | Skill failure event tracking for interceptor. | ✅ |
| `_tool_execution_lifecycle.py` | Internal | Tool execution lifecycle hooks. | ✅ |
| `_tool_guards.py` | Internal | Guard modules orchestrated by tool_interceptor. | ✅ |
| `_tool_helpers.py` | Internal | Stateless helpers for tool_interceptor_middleware. | ✅ |
| `completion_guard.py` | Core | Finish gate + Mixed Message Guard for code tasks. Exports `is_mutating_tool()` SSOT for side-effect tool detection (Cron post-run verify, completion gate). | ✅ |
| `clarification_guard_middleware.py` | Core | Enforces single `ask_question_tool` call per turn; blocks coexisting tool calls with synthetic errors. | ✅ |
| `completion_guard_checklist.py` | Internal | Verification command classification + checklist builder for CompletionGuard. | ✅ |
| `concurrency_limiter.py` | Core | Subagent Semaphore by agent_type. | ✅ |
| `concurrency_router.py` | Core | Smart concurrency routing with safety_dispatcher. | ✅ |
| `context_pipeline_helpers.py` | Internal | Compression intent, cache feedback, schema fingerprint. | ✅ |
| `context_pipeline_middleware.py` | Core | `create_context_pipeline_middleware` factory. | ✅ |
| `dangling_tool_call_middleware.py` | Core | Repair dangling tool_calls for strict providers. | ✅ |
| `deferred_index_middleware.py` | Core | Inject `<available-deferred-tools>` stable system index once per thread. | ✅ |
| `_skill_tool_choice.py` | Internal | Build OpenAI ``allowed_tools`` tool_choice for skill attenuation (cache-safe). | ✅ |
| `deferred_tool_middleware.py` | Core | ToolNode resolution for DISCOVERABLE tools; skill attenuation via ``tool_choice.allowed_tools``. Does not mutate `request.tools`. | ✅ |
| `debug_logger_middleware.py` | Core | Full message list debug logging. | ✅ |
| `filesystem_search_middleware.py` | Core | Inject glob/grep workspace search tools. | ✅ |
| `memory_context_middleware.py` | Core | `<user_memory_context>` + scope boundary + untrusted data wrapping. | ✅ |
| `memory_context_format.py` | Core | Formatting helpers for memory context injection | ✅ |
| `progress_middleware.py` | Core | Active todo focus injection into last HumanMessage. | ✅ |
| `rate_limit.py` | Core | Proactive provider 429 throttling. | ✅ |
| `replan_middleware.py` | Core | Dynamic replan loop on tool errors. | ✅ |
| `safety_dispatcher.py` | Core | safe→concurrent / unsafe→serial tool routing. | ✅ |
| `security_boundary_middleware.py` | Core | Security boundary enforcement. | ✅ |
| `security_guardrail_middleware.py` | Core | Security guardrail enforcement. | ✅ |
| `subagent_limit_middleware.py` | Core | Max concurrent subagents per turn. | ✅ |
| `task_adaptive_middleware.py` | Core | Trace-analytics JIT execution constraints. | ✅ |
| `tool_call_dedup_middleware.py` | Core | tool_call_id deduplication. | ✅ |
| `tool_executor.py` | Core | Tool execution with timeout/retry/backoff. | ✅ |
| `tool_interceptor_middleware.py` | Core | Single interception point for all tool calls. | ✅ |

| Submodule | Description |
|-----------|-------------|
| `approval/` | HITL approval queue, batch, scheduler. See [approval/_ARCH.md](approval/_ARCH.md). |
| `approval_interception/` | Approval interception recognizer. See [approval_interception/_ARCH.md](approval_interception/_ARCH.md). |
| `guardrails/` | Guardrail provider chain + GuardrailMiddleware. See [guardrails/_ARCH.md](guardrails/_ARCH.md). |

## Key Dependencies

- `agent/context_management/` — context pipeline processors
- `agent/security/` — tool result validation, guards
- `infra`
- `observability`
- `toolkits`
- `utils`
