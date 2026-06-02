# middlewares/

## Overview
Agent middleware system exports. Provides the complete middleware stack (context management, debug logging, tool interception, filesystem search).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent middleware system exports. Provides the complete middleware stack (context management, debug l | ✅ |
| _session_context.py | Internal | Middleware session context — shared ContextVars for the middleware chain. | ✅ |
| completion_guard.py | Core | Fills the "Agent finishing" gap. CRITICAL blocking for code modification tasks without verification (tests/lint/type-check). Non-critical tasks pass through immediately. Filters internal tool (`_`-prefixed) CallRecords. Uses module-level state (not ContextVar) for cross-node persistence in LangGraph. Includes Mixed Message Guard that strips read-only tool_calls when content is already a substantive final answer. | ✅ |
| concurrency_limiter.py | Core | Subagent concurrency limiter middleware. Limits concurrent execution count by agent_type to prevent  | ✅ |
| context_pipeline_helpers.py | Internal | Helper layer for context pipeline middleware. Parses compression intent, resolves provider cache usage feedback, and fingerprints active tool schemas with stable JSON canonicalization for cache break attribution. | ✅ |
| context_pipeline_middleware.py | Core | Provides create_context_pipeline_middleware. | ✅ |
| dangling_tool_call_middleware.py | Core | Dangling tool call repair middleware. | ✅ |
| deferred_tool_middleware.py | Core | Parses `<AutoMountTools>` from discover_capability_tool; augments model tools and supplies deferred `BaseTool` at ToolNode via `awrap_tool_call`. | ✅ |
| debug_logger_middleware.py | Core | Provides debug_logger_middleware. | ✅ |
| filesystem_search_middleware.py | Core | Provides FilesystemFileSearchMiddleware, create_filesystem_search_middleware. | ✅ |
| memory_context_middleware.py | Core | Memory context — Stable `<user_memory_context>` (System) + learned `<<<UNTRUSTED_DATA>>>` (Human via `wrap_untrusted`). Unified budget. | ✅ |
| permission_middleware.py | Core | Permission check middleware (framework layer). Decoupled from the business layer via callback mechan | ✅ |
| planner_middleware.py | Core | Middleware to inject plan blueprint, anti-drift reminder, and decision log into HumanMessage (via request.override, cache-safe). | ✅ |
| rate_limit.py | Core | Proactive rate-limit throttling middleware. Detects provider from HTTP header signatures, sleeps only when all tracked providers are exhausted (shortest recovery, capped at 120s), and emits SSE events for frontend awareness. | ✅ |
| replan_middleware.py | Core | Dynamic Replan Loop Middleware. Per-tool error counting prevents unrelated tool successes from resetting the counter for a persistently failing tool. | ✅ |
| safety_dispatcher.py | Core | Tool concurrency safety dispatcher. Uses resolve_safety_metadata (3-level fallback: built-in → MCP dynamic → fail-closed) to route concurrent vs. serial execution. | ✅ |
| security_boundary_middleware.py | Core | Security boundary middleware. | ✅ |
| security_guardrail_middleware.py | Core | Security guardrail middleware. | ✅ |
| subagent_limit_middleware.py | Core | Subagent limit middleware. Ensures the LLM cannot spawn more than MAX_CONCURRENT_SUBAGENTS | ✅ |
| task_adaptive_middleware.py | Core | Applies execution constraints BEFORE the agent runs based on Trace Analytics. | ✅ |
| tool_call_dedup_middleware.py | Core | Tool call deduplication middleware. Ensures each tool_call_id appears at most | ✅ |
| _mutation_verifier.py | Internal | Per-turn file mutation verifier. Tracks file-mutating tool outcomes via ContextVar; surfaces failures as SSE events to prevent model hallucination of success. | ✅ |
| _tool_helpers.py | Internal | Stateless helper functions for tool_interceptor_middleware | ✅ |
| tool_executor.py | Core | Tool execution engine with timeout, retry, and exponential backoff | ✅ |
| tool_interceptor_middleware.py | Core | Single interception point for all tool calls — orchestrates guards, emits structured archive-restore blocked status, and publishes framework-level skill failure events with session/LoopGuard metadata while filtering policy blocks. Converts ToolStuckException to GraphInterrupt via `interrupt()` to truly halt agent execution when stuck. | ✅ |

| Submodule | Description |
|-----------|-------------|
| approval/ | Tool approval subsystem — Human-in-the-Loop approval flow. |
| approval_interception/ | Approval Interception Middleware. |

## Key Dependencies

- `infra`
- `observability`
- `toolkits`
- `utils`
