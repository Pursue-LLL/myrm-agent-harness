# guards/

## Overview
Session-level security guards integrated into tool_interceptor_middleware.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Session-level security guards integrated into tool_interceptor_middleware. | — |
| context_budget.py | Core | Layer-0 context budget guard; oversized tool results persist via UECD `.context/.../evicted/` when session context exists, else truncate. Emits `evicted_ref` for GUI via `_tool_guards`. | ✅ |
| estop.py | Core | Global guard. Checked as the very first step in tool_interceptor_middleware. State persisted at `{MYRM_DATA_DIR or ~/.myrm}/.estop_state.json`. | ✅ |
| frequency_guard.py | Core | Layer 5 (Anti-Abuse) guard. Detects tool call frequency anomalies (global and per-tool) for DoS prevention and cost overrun protection. | ✅ |
| tool_turn_budget_guard.py | Core | Layer 5 (Anti-Abuse) guard. Per-user-turn budget for high-cost tools (default: web_search_tool 20 search queries per active_message_id; other tools 1 unit per call). | ✅ |
| privacy_tracker.py | Shim | Re-exports `core.security.guards.privacy_tracker` for stable import paths. | ✅ |
| prompt_budget.py | Core | Prompt Budget Guard. | ✅ |
| skill_approval_hook.py | Core | Integrated into tool_interceptor_middleware between the onion policy and execution. | ✅ |
| ssrf_guard.py | Shim | Re-exports `core.security.guards.ssrf` for stable `agent.security.guards.*` import paths. | ✅ |
| taint_tracker.py | Core | Layer 2 enhancement. Tracks information flow labels (prompt→command injection prevention). | ✅ |

| Submodule | Description |
|-----------|-------------|
| loop_guard/ | Unified inefficiency detection (repetition, ping-pong, no-progress, divergence, output-diminishing, error-signature). Contains LoopGuard, detection algorithms, types, stats, and suggestions. |

## Key Dependencies

- `infra`
- `runtime`
- `utils`
