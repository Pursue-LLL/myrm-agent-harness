# coordination — Subagent P2P Mailbox

## 架构概述

Session-scoped in-memory queues with optional workspace JSONL persistence (`teammate_mailbox_{session_id}.jsonl`). Used for sibling subagent direct messaging without polluting parent context.

- **Rate limit**: sliding window 30 sends / 60s per `from_task_id`; failures return `TeammateSendResult.error`.
- **Target validation**: `send_teammate_message_tool` rejects unknown `target_task_id` (not in active roster).
- **JSONL retention**: trim file to last 1000 lines after persist.
- **GUI SSE (M1)**: `send_teammate_message_tool` success → `emit_teammate_message_sse` via `ToolProgressSink`; drain path still emits for recipient turn.

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `types.py` | 核心 | `TeammateMessage` dataclass | ✅ |
| `mailbox.py` | 核心 | `TeammateMailbox`, send/drain/history/group | ✅ |
| `__init__.py` | 导出 | Public API surface | ✅ |

## 模块依赖

- `agent.sub_agents.manager` — spawn registers / complete unregisters roster on mailbox
- `agent.meta_tools.spawn_subagent.send_teammate_tool` — LLM send path
- `app.api.agents.subagents` — API hydrate via `list_teammate_history`
