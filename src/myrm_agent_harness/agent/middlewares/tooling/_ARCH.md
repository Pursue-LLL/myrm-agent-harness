# tooling/

## Overview

Single interception point for all tool calls. The interceptor orchestrates
stateless guards and lifecycle hooks; each guard is an independent module.

Detailed design: [MIDDLEWARE_SYSTEM.md](../MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for tool_interceptor and LoopGuard accessors. | — |
| `tool_interceptor_middleware.py` | Core | Single interception point for all tool calls; session-key registry keeps LoopGuard across ContextVar loss after HITL resume; `reset_loop_guard(is_resume=True)` preserves error signatures and the CallRecord window. | ✅ |
| `tool_executor.py` | Core | Tool execution with timeout/retry/backoff; propagates `ToolError.error_category` into ToolMessage for SSE. | ✅ |
| `tool_history_hygiene.py` | Core | Sanitize pipeline: within-AIMessage re-id → ToolMessage dedup (keep-last) → cross-turn re-id; exports `sanitize_tool_history()` for grace-call / oneshot retry. Runs before dangling repair. | ✅ |
| `dangling_tool_call_middleware.py` | Core | Repair malformed tool histories for strict providers: sanitize malformed calls, patch dangling tool_calls, drop orphan ToolMessages; exports `repair_dangling_tool_calls()` for direct LLM invocations (grace-call path). | ✅ |
| `_tool_guards.py` | Internal | Pre-call and post-call guard orchestration (e-stop, loop budget, circuit breaker, turn budget). | ✅ |
| `_tool_helpers.py` | Internal | Stateless helpers for `tool_interceptor_middleware` (output normalization, trust attenuation, retry classification, terminal error classification). | ✅ |
| `_tool_execution_lifecycle.py` | Internal | Dynamic tool resolution, heartbeat emission during long-running tool execution, and execution lifecycle hooks. | ✅ |
| `_runtime_tool_governance.py` | Internal | Per-turn intent-aware tool narrowing (UI + readonly gates) and `compute_turn_allowed_names()` merged allowlist (prefix-cache safe). | ✅ |
| `_mutation_verifier.py` | Internal | Per-turn file mutation verifier → SSE on failure. | ✅ |
| `_skill_failure_tracking.py` | Internal | Skill failure event tracking for interceptor. | ✅ |
| `_skill_tool_choice.py` | Internal | Build OpenAI `allowed_tools` tool_choice for skill attenuation (prefix-cache safe). | ✅ |
| `skill_attenuation_middleware.py` | Core | Skill attenuation via `tool_choice.allowed_tools` when provider supports it; skips model-layer hint otherwise; execution SSOT via ContextVar + `check_trust_attenuation`; dynamic tool resolution for ToolNode. Does not mutate `request.tools`. | ✅ |

## Key Dependencies

- `agent.middlewares._session_context` — shared ContextVars for the middleware chain
- `agent.security.guards.loop_guard` — LoopGuard, CallRecord, ToolGroup
- `agent.security` — tool result validation, guards
