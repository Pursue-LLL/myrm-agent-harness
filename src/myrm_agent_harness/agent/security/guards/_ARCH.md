# guards/

## Overview
Session-level security guards integrated into tool_interceptor_middleware.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Session-level security guards integrated into tool_interceptor_middleware. | — |
| _loop_detectors.py | Core | Mixin providing loop detection algorithms (repetition, ping-pong, no-progress WARN/BREAK, output-diminishing, divergence, consecutive-failures, error-signature). Inherited by LoopGuard. | ✅ |
| context_budget.py | Core | Session-level guard. Integrated into tool_interceptor_middleware at | ✅ |
| estop.py | Core | Global guard. Checked as the very first step in tool_interceptor_middleware. State persisted at `{MYRM_DATA_DIR or ~/.myrm}/.estop_state.json`. | ✅ |
| frequency_guard.py | Core | Layer 5 (Anti-Abuse) guard. Detects tool call frequency anomalies (global and per-tool) for DoS prevention and cost overrun protection. | ✅ |
| loop_guard.py | Core | Session-level safety guard integrated into tool_interceptor_middleware; detects repetition, ping-pong, no-progress (graduated WARN→BREAK), divergence, consecutive failures, output-diminishing, and cross-tool error signature repetition. Iteration budget thresholds are dynamically computed from `graph_recursion_limit` via `_configure_budget`; budget exhaustion raises ToolStuckException (converted to GraphInterrupt by middleware). Returns loop pattern metadata for runtime skill failure evidence. | ✅ |
| loop_guard_stats.py | Core | Optional persistent statistics layer for LoopGuard. Records loop events | ✅ |
| loop_guard_types.py | Config | Core types for the unified loop guard. Provides verdict types with optional loop pattern metadata | ✅ |
| privacy_tracker.py | Core | Per-turn privacy state tracker. ContextVar session-scoped, independently evaluates each turn for pri | ✅ |
| prompt_budget.py | Core | Prompt Budget Guard. | ✅ |
| skill_approval_hook.py | Core | Integrated into tool_interceptor_middleware between the onion policy | ✅ |
| ssrf_guard.py | Core | Standalone guard module. Called by browser toolkit (navigation) and | ✅ |
| taint_tracker.py | Core | Layer 2 enhancement. Sits between tool_interceptor (records taint after | ✅ |

| Submodule | Description |
|-----------|-------------|
| loop_suggestions/ | Suggestion generation subsystem for LoopGuard. Analyzes parameters and |

## Key Dependencies

- `infra`
- `runtime`
- `utils`
