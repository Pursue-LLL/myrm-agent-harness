# spawn_subagent/

## Overview

LLM 子 Agent 委派元工具：`delegate_task_tool`（mode=single|batch|parallel）+ `subagent_control_tool`（action=list|cancel|steer）+ orchestrator 专用 `send_teammate_message_tool`。与 Dynamic Workflow PTC `spawn_subagent`（`agent/dynamic_workflow/tools.py`）共用 `_spawn_child()` 下游，但 PTC 名不在 `_TOOL_LAYERS` 登记。

Detailed design: [SUB_AGENT_SYSTEM.md](../../sub_agents/SUB_AGENT_SYSTEM.md) · [META_TOOLS_SYSTEM.md](../META_TOOLS_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for spawn/delegation meta-tools | — |
| agent_manage_tool.py | Core | `subagent_control_tool` unified list/cancel/steer surface | ✅ |
| send_teammate_tool.py | Core | `send_teammate_message_tool`: sibling P2P mailbox | ✅ |
| delegate_task_tool.py | Core | `delegate_task_tool` factory + `update_delegate_task_description` | ✅ |
| delegation_pause_gate.py | Core | Session-scoped pause gate for new spawns (REST + tool entry) | ✅ |
| _manager_control.py (via manager) | Core | list/cancel/steer + running token observability patch | ✅ |
| _delegate_budget.py | Internal | Budget admission, caching, dynamic roster for delegate_task_tool | ✅ |
| _delegate_batch.py | Internal | `execute_batch_delegation` / `execute_parallel_delegation` engines | ✅ |

## Key Dependencies

- `agent.sub_agents` (SubagentManager, catalog, manifest)
- `agent.parallel.runner` (batch concurrent execution)
