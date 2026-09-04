# Continual Adaptation Subsystem (`agent.continual`)

## Architecture Index

| File | Classification | Responsibility | Status |
| --- | --- | --- | --- |
| `__init__.py` | Package | Public exports for Continual Adaptation (`SessionOverlay`, `SessionOverlayManager`, `synthesize_fault_site_overlay`). | ✅ |
| `overlay.py` | Core | Session-scoped fault-site overlay schema (4 shells: prompt_patch, skill_variant, subagent_config, procedural_memory), TTL turn ticking, non-destructive rollbacks, and deterministic fault-site overlay synthesizer. | ✅ |

## Design Principles
1. **Zero-Reset Recovery**: Solves deep-episode failures without discarding long-running agent contexts or rolling back checkpoints.
2. **Session-Scoped Boundary**: Overlays apply only to the active `session_id` and automatically expire or roll back upon regress; never mutate global `SkillStore` directly without post-run graduation approval.
3. **Prompt Cache Preservation**: Dynamic prompt patches are strictly injected at the epilogue of dynamic contexts, preserving static system prompt prefixes with 100% byte parity.
