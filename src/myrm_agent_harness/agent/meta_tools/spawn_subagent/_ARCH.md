# spawn_subagent/

## Overview

LLM 子 Agent 委派元工具：`delegate_task_tool`（mode=single|batch|parallel|council|alternatives）+ `subagent_control_tool`（action=list|cancel|steer|wait，位于 `agent_manage_tool.py`）+ orchestrator 专用 `send_teammate_message_tool`。与 **DW PTC** `spawn_subagent`（`agent/dynamic_workflow/tools.py`）共用 `_spawn_child()` 下游与 **`agent/sub_agents/spawn_prep.py`** spawn 准备 SSOT（含 `coerce_spawn_readonly` readonly floor），但 DW PTC 工具名不在 `_TOOL_LAYERS` 登记。

Detailed design: [SUB_AGENT_SYSTEM.md](../../sub_agents/SUB_AGENT_SYSTEM.md) · [META_TOOLS_SYSTEM.md](../META_TOOLS_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for spawn/delegation meta-tools | — |
| agent_manage_tool.py | Core | `subagent_control_tool` unified list/cancel/steer/wait surface | ✅ |
| send_teammate_tool.py | Core | `send_teammate_message_tool`: sibling P2P mailbox | ✅ |
| delegate_task_tool.py | Core | `delegate_task_tool` factory (mode=single\|batch\|parallel\|council\|alternatives): routes `mode` to its executor + `update_delegate_task_description` | ✅ |
| delegation_pause_gate.py | Core | Session-scoped pause gate for new spawns (REST + tool entry) | ✅ |
| _manager_control.py (via manager) | Core | list/cancel/steer/wait + running token observability patch | ✅ |
| _delegate_budget.py | Internal | Budget admission, the repeated-delegation fingerprint (`_compute_payload_hash` covers task, context, role, `effective_readonly`, `complexity_tier` and the verification options), dynamic roster for delegate_task_tool | ✅ |
| _delegate_input.py | Internal | `DelegateTaskInput`: the LLM-facing args schema of delegate_task | ✅ |
| _delegate_single.py | Internal | `execute_single_delegation` — agent-type admission, repeated-delegation guard, role/readonly/spawn policy, OCap handle, spawn or verification loop, approval resume. The delegation id and every approval step come from the manager's `approval_journal` (LangGraph re-executes the call after each approval), so each approval reaches the subagent that asked for it exactly once and in order, and the repeated-delegation guard does not mistake a re-execution for a repeat. A single spawn with a `verifier_prompt` picks its verifier with `sub_agents/verifier_selection.resolve_verifier` and returns an error dict, before any worker spawns, for a verifier that cannot run commands | ✅ |
| _delegate_batch.py | Internal | `execute_batch_delegation` / tournament bracket; winner ISOLATED_COPY merge via `build_merge_snapshot_context`. A cost refusal carries the person's own words in `rejection_feedback` (read through `core.security.hitl_decision.rejection_feedback`) when they gave any | ✅ |
| _delegate_cognitive.py | Internal | `execute_cognitive_mode` — council cross-review and alternatives multi-solution execution with pre-flight cost estimation. A cost refusal carries the person's own words in `rejection_feedback` when they gave any | ✅ |

## Key Dependencies

- `agent.sub_agents` (SubagentManager, catalog, manifest, orchestrator)
- `agent.parallel.runner` (batch concurrent execution)
- `utils.chat_utils` (extract_answer_text — tournament judge 响应提取)
