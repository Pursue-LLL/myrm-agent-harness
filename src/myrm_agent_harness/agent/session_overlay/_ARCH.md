# session_overlay/

## Overview
Continual fault-site session overlay subsystem for zero-reset agent self-healing.
Implements the Continual Harness philosophy: modifying localized runtime shells
(prompts, temporary skill variants, subagent configs, procedural memories)
at failure sites without resetting agent state, checkpoints, or sandboxes.

## File Index

| File | Role | Description |
|------|------|-------------|
| `schema.py` | Core Data Contracts | SSOT enum and immutable dataclasses: `OverlayScope`, `OverlayTargetType`, `SessionOverlay`, `OverlayStatus`, and `SessionOverlaySnapshot`. |
| `manager.py` | Lifecycle Controller | ContextVar and session-bound `SessionOverlayManager` enforcing TTL turn-decrement, maximum active caps (≤2), and the single-shot Trial & Rollback Guard. |
| `synthesizer.py` | Rule Engine | Dual-track zero-LLM synthesis from tool execution exceptions (L0 regex + L1 ValidationError loc parsing) and LoopGuard stall warnings. |
| `__init__.py` | Package Exports | Canonical public exports for harness runtime and middleware layers. |

## Key Invariants
1. **Scope Isolation**: Overlays operate strictly within `Session` or `Task` memory scopes. They never mutate global SkillStore or global profile assets directly.
2. **Prompt Cache Safety**: Negative constraints and adapters attach locally to the current turn's tool error feedback or dynamic turn tail. They never mutate static system prompt prefixes.
3. **Trial & Rollback Guard**: An active overlay receives a single-shot trial. If an identical failure signature recurs under the overlay, it is instantly rolled back to prevent patch cascade failures.
4. **Post-Run Assetization**: Successfully verified overlays export to Growth / PendingEvolutions pipelines with the `continual_overlay` tag for human review (HITL).
