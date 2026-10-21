# guards/

## Overview
Session-level security guards integrated into tool_interceptor_middleware.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Session-level security guards integrated into tool_interceptor_middleware. | — |
| context_budget.py | Core | Layer-0 context budget guard; oversized tool results persist via UECD `.context/.../evicted/` when session context exists, else truncate. Emits `evicted_ref` for GUI via `_tool_guards`. Per-run cumulative budget cleared via `reset_context_budget_guard()` in `reset_all_guards()`; preserved on approval resume (`is_resume=True`). | ✅ |
| estop.py | Core | Global guard. Checked as the very first step in tool_interceptor_middleware. State persisted at `{MYRM_DATA_DIR or ~/.myrm}/.estop_state.json`. | ✅ |
| frequency_guard.py | Core | Layer 5 (Anti-Abuse) guard. Detects tool call frequency anomalies (global and per-tool) for DoS prevention and cost overrun protection. | ✅ |
| tool_turn_budget_guard.py | Core | Layer 5 (Anti-Abuse) guard. Per-user-turn budget for high-cost tools (default: web_search_tool 20 search queries per active_message_id; other tools 1 unit per call). | ✅ |
| privacy_tracker.py | Shim | Re-exports `core.security.guards.privacy_tracker` for stable import paths. | ✅ |
| prompt_budget.py | Core | Prompt Budget Guard. | ✅ |
| skill_approval_hook.py | Core | Integrated into tool_interceptor_middleware between the onion policy and execution. | ✅ |
| ssrf_guard.py | Shim | Re-exports `core.security.guards.ssrf` for stable `agent.security.guards.*` import paths. | ✅ |
| taint_tracker.py | Core | Tracks session information flow labels and enforces file-to-egress correlation guards with session allowlist. | ✅ |
| untrusted_ingress_fence.py | Core | Layer 2 runtime privilege stripping fence for external untrusted inbound messages; denies destructive shell/write, long-term memory mutation (save/manage), desktop control & capture, subagent escalation, cron, and skill management tools at tool-call time. `set_untrusted_ingress` flags a whole turn; `untrusted_ingress_scope` flags only the block it wraps (and tasks spawned inside it) and restores the prior state on exit, for hosts that fan work out from a long-lived loop. | ✅ |

| Submodule | Description |
|-----------|-------------|
| loop_guard/ | Unified inefficiency detection (repetition, ping-pong, no-progress, divergence, output-diminishing, error-signature). Contains LoopGuard, detection algorithms, types, stats, and suggestions. |

## Key Dependencies

- `infra`
- `runtime`
- `utils`
