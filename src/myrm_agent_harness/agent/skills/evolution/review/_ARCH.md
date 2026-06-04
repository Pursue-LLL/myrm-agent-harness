# review/

## Overview
Background silent review and skill distillation system. Asynchronously reviews conversation history after session completion to extract reusable skill patterns.
It implements a robust **10-Dimensional Semantic Rubric** combined with **Objective Sandbox Metrics Pre-Screening**.

## Pre-Screener (ExecutionMetrics)

Before invoking the LLM, the `_skill_agent_review.py` interceptor checks `ExecutionMetrics`. If the trajectory yielded 0 successful tool executions (`total_success == 0`), the extraction is physically blocked. This prevents LLM hallucination where the LLM might incorrectly score a completely failed attempt as a success.

## Review Prompt Design

The `_REVIEW_PROMPT_TEMPLATE` and `SkillExtractionRubric` in `reviewer.py` implement a multi-layered guidance system using a **10-Dimensional Sandbox-Ready Rubric**:

1. **Structure & Frontmatter** (`structure_score`)
2. **Workflow Clarity** (`workflow_clarity_score`)
3. **Failure Mode Encoding** (`failure_mode_score`) — Forces extraction of `if-then` fallback branches.
4. **Anti-patterns** (`anti_pattern_score`) — Explicitly records what NOT to do.
5. **Human-in-the-Loop** (`human_in_loop_score`)
6. **Resource Integration** (`resource_integration_score`)
7. **Anti-fluff** (`anti_fluff_score`)
8. **Anti-fragmentation** (`anti_fragmentation_score`)
9. **Sandbox Compatibility** (`sandbox_compatibility_score`) — Ensures skills respect `Agent-in-Sandbox` constraints.
10. **Multi-Agent Isolation** (`multi_agent_isolation_score`) — Ensures skills specify `Agent_ID` limits and don't pollute other agents.

### Red-Line Veto Mechanism (安全红线一票否决)

The system relies on a weighted average `total_score` to evaluate overall skill quality. However, to prevent critical security or structural flaws from being masked by high scores in formatting or syntax, a **Red-Line Veto** is strictly enforced. 

If any of the following scores fall below the minimum threshold (0.6):
- `sandbox_compatibility_score` (protects persistent volumes from escape/destructive code)
- `anti_pattern_score` (prevents toxic anti-patterns)
- `anti_fragmentation_score` (prevents hyper-specific, non-reusable snippets)

The extraction is instantly and physically rejected (`result_type="nothing"` fallback), overriding the `total_score` mathematical average. This ensures 100% data safety in the Agent-in-Sandbox multi-tenant architecture.

Additional constraints:
- **Anti-Drift Guard** — Rejects learning from drifted/failed execution paths
- **DO NOT CAPTURE rules** — Prevents harmful knowledge fixation (env failures, tool negative claims, transient errors, one-off tasks)
- **Class-Level Naming Constraint** — Forbids fix-/debug-/audit- prefixes and session-specific names
- **Priority Order** — Biases toward patching existing skills: PATCH LOADED > PATCH UMBRELLA > CREATE NEW

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Background silent review and skill distillation system. Asynchronously reviews conversation history  | ✅ |
| evaluator.py | Core | Heartbeat evaluator. Scores conversation health based on expression_volume and task_complexity metri | ✅ |
| pruner.py | Core | Provides prune_trajectory. | ✅ |
| reviewer.py | Core | Skill review engine. Calls cheap LLM to extract skills using 10-Dim Rubric. | ✅ |

## Key Dependencies

- `utils`
- `toolkits.code_execution.executors` (for `ExecutionMetrics` in Pre-Screener)