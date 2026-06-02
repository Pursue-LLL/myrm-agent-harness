# review/

## Overview
Background silent review and skill distillation system. Asynchronously reviews conversation history after session completion to extract reusable skill patterns.

## Review Prompt Design

The `_REVIEW_PROMPT_TEMPLATE` in `reviewer.py` implements a multi-layered guidance system:

1. **Anti-Drift Guard** — Rejects learning from drifted/failed execution paths
2. **DO NOT CAPTURE rules** — Prevents harmful knowledge fixation (env failures, tool negative claims, transient errors, one-off tasks)
3. **Class-Level Naming Constraint** — Forbids fix-/debug-/audit- prefixes and session-specific names
4. **Priority Order** — Biases toward patching existing skills: PATCH LOADED > PATCH UMBRELLA > CREATE NEW

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Background silent review and skill distillation system. Asynchronously reviews conversation history  | ✅ |
| evaluator.py | Core | Heartbeat evaluator. Scores conversation health based on expression_volume and task_complexity metri | ✅ |
| pruner.py | Core | Provides prune_trajectory. | ✅ |
| reviewer.py | Core | Skill review engine. Calls cheap LLM to judge if a conversation trajectory | ✅ |

## Key Dependencies

- `utils`
