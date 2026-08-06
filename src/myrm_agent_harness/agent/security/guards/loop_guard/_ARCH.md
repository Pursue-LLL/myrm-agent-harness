# loop_guard/

## Overview
Unified inefficiency detection for Agent sessions — repetition, ping-pong,
no-progress, divergence, output diminishing, and cross-tool error signature
repetition. Provides WARN/BREAK verdicts with context-aware suggestions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports public API (LoopGuard, types, suggestions). | — |
| guard.py | Core | Session-level LoopGuard with BREAK/WARN/ALLOW verdicts, loop pattern metadata, smart suggestions, metrics, quality feedback, sandbox_boundary_triggered flag, and reset(preserve_call_window=True) for HITL resume. | ✅ |
| detectors.py | Core | Mixin providing detection algorithms (repetition, ping-pong, no-progress, divergence, output-diminishing, consecutive-failures, error-signature). Inherited by LoopGuard. | ✅ |
| types.py | Config | Core types — LoopAction, LoopVerdict, LoopKind, AgentPhase, SuccessLevel, WarningLevel, ErrorPattern, ToolGroup, VerificationCategory, LoopGuardMetrics, CallRecord. | ✅ |
| stats.py | Core | Optional persistent statistics layer. Records loop events to SQLite for data-driven threshold tuning. | ✅ |

| Submodule | Description |
|-----------|-------------|
| suggestions/ | Context-aware suggestion generation — 16 tools across 8 specialized modules. |

## Key Dependencies

- `core/security` (indirectly, via parent guards)
