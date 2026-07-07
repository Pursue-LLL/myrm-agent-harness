# spawn_subagent/

## Overview

LLM 子 Agent 委派元工具（`delegate_task_tool` 等）。与 Dynamic Workflow PTC `spawn_subagent`（`agent/dynamic_workflow/tools.py`）共用 `_spawn_child()` 下游，但不在 `_TOOL_LAYERS` 登记 PTC 名。

Detailed design: [SUB_AGENT_SYSTEM.md](../../sub_agents/SUB_AGENT_SYSTEM.md) · [META_TOOLS_SYSTEM.md](../META_TOOLS_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Spawn subagent meta-tool module. | — |
| agent_manage_tool.py | Core | Subagent management meta-tool. Provides LLM with runtime observability and control over child agents | ✅ |
| send_teammate_tool.py | Core | `send_teammate_message_tool`: sibling P2P mailbox; on success calls `emit_teammate_message_sse`; returns `active_teammates` roster | ✅ |
| delegate_task_tool.py | Core | Unified delegate_task_tool tool factory (`create_delegate_task_tool`, `update_delegate_task_description`). Supports granular adversarial verification. Re-exports batch/parallel from `_delegate_batch`. | ✅ |
| _delegate_budget.py | Internal | Budget admission, policy enforcement, result caching, payload fingerprinting, generic cost estimation (`_estimate_batch_cost`), and dynamic tool description for delegate_task_tool. | ✅ |
| _delegate_batch.py | Internal | Batch and parallel delegation tool factories. Supports tournament mode, adversarial verification, and pre-flight cost approval via `interrupt()`. | ✅ |

## Key Dependencies

- `toolkits`
- `utils`
