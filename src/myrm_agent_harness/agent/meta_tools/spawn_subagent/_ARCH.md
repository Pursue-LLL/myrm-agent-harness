# spawn_subagent/

## Overview
Spawn subagent meta-tool module.
Provides subagent spawning, batch delegation, and catalog-driven prompt shaping with readonly, control-scope, memory-isolation, and complexity-tier routing.

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
