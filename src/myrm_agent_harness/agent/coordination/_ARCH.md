# coordination — Subagent P2P Mailbox

## 架构概述

Session-scoped in-memory queues with optional workspace JSONL persistence (`teammate_mailbox_{session_id}.jsonl`). Used for sibling subagent direct messaging without polluting parent context.

- **Rate limit**: sliding window 30 sends / 60s per `from_task_id`; failures return `TeammateSendResult.error`.
- **Target validation**: `send_teammate_message_tool` rejects unknown `target_task_id` (not in active roster).
- **JSONL retention**: trim file to last 1000 lines after persist.
- **GUI SSE (M1)**: `send_teammate_message_tool` success → `emit_teammate_message_sse` via `ToolProgressSink`; drain path still emits for recipient turn.
- **Roster injection**: `drain_teammate_messages_for_task(include_roster=True)` appends `<active_teammates>` XML so the LLM knows sibling task IDs for P2P messaging. The `_drain_teammate_messages` closure in `agent_runtime.py` uses a `_roster_injected` flag to inject roster on the first turn and refresh it only when new messages arrive.

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `types.py` | 核心 | `TeammateMessage` dataclass | ✅ |
| `mailbox.py` | 核心 | `TeammateMailbox`, send/drain/history/group | ✅ |
| `adaptive_wakeup/` | 核心 | 自适应唤醒驱动与有界轮次熔断保护 (types, budget_tracker, adaptive_router) | ✅ |
| `bot_mode/` | 核心 | 具名智能体工位花名册、Bot-to-Bot 异步发信与 @mention 寻址投递信箱中继协议 (types, roster, mailbox_relay) | ✅ |
| `squad_composition/` | 核心 | 总编排智能体自动组队、Model 留白两阶段向导与动态算力预算切分引擎 (types, budget_allocator, blueprint_composer) | ✅ |
| `workspace_blueprint/` | 核心 | 按项目/工作区自动复用团队 Blueprint 绑定与解析引擎 (types, binding_store) | ✅ |
| `scope_guardrails/` | 核心 | Orchestrator 越权防护与安全建队模式收敛审核引擎 (types, guardrails_engine) | ✅ |
| `autonomous_loop/` | 核心 | Goal/Kanban 驱动自主编排循环与安全步数看门狗引擎 (types, loop_controller) | ✅ |
| `tri_role/` | 核心 | 规划-执行-可扩展评估三权分立与跨会话工件无损交接管线 (types, pipeline_coordinator) | ✅ |
| `multi_bot_focus/` | 核心 | 多Bot协同会话Mention焦点动态绑定与长会话防抖压实引擎 (types, focus_compactor) | ✅ |
| `wave_orchestrator/` | 核心 | 编码型 Agent Profile 可选预置与多阶段 Wave 波次流水线编排引擎 (types, wave_engine) | ✅ |
| `__init__.py` | 导出 | Public API surface | ✅ |

## 模块依赖

- `agent.sub_agents.manager` — spawn registers / complete unregisters roster on mailbox
- `agent.meta_tools.spawn_subagent.send_teammate_tool` — LLM send path
- `app.api.agents.subagents` — API hydrate via `list_teammate_history`
- `app.services.agent.wakeup_handler` & `background_job_finish_handler` — adaptive followup/inject dispatching

