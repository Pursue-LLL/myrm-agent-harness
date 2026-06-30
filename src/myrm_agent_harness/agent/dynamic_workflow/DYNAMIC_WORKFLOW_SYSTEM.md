# Dynamic Workflow System Design

> 第三代编排层。LLM 生成 Python 编排脚本，在 PTC 沙箱中并发 spawn 子 Agent，突破单 Agent 上下文限制。

---

## 设计目标

1. **Code-as-Orchestrator**：循环/分支/并行逻辑交给 Python，保持 orchestrator LLM 上下文干净
2. **与 delegate 同路径**：`SpawnSubagentTool` → `parent_agent._spawn_child()`，工具/registry/预算与 `delegate_task_tool` 一致
3. ** durable 执行**：SQLite Event Store + deterministic `workflow_id`，崩溃后可 replay 已完成子任务
4. **SSE 兼容**：标准 `AgentEventType`（message/message_end/status），前端无需新类型

---

## 系统架构

```
Server (use_workflow=True)
       ↓
run_dynamic_workflow_stream (__init__.py)
       ↓
LLM → Python 编排脚本 (ORCHESTRATOR_PROMPT + SubagentCatalog hint)
       ↓
PTC Sandbox
       ↓
SpawnSubagentTool / NotifyProgressTool (tools.py)
       ↓
WorkflowEventStore (store.py) — L2 cache / replay
       ↓
Summarization LLM → 用户可读 Markdown
```

---

## 核心文件

| 文件 | 职责 |
|------|------|
| `__init__.py` | `run_dynamic_workflow_stream` 入口；类型发现；阶段 cancel 检查 |
| `store.py` | SQLite Event Sourcing；`harden_connection_sync(CACHE)` |
| `tools.py` | `SpawnSubagentTool`（含 readonly 双保护）、`NotifyProgressTool` |

---

## 与 sub_agents / parallel 边界

| | dynamic_workflow | parallel | sub_agents |
|--|------------------|----------|------------|
| 触发 | Server workflow 模式 | batch_delegate / swarm | 通用委派全栈 |
| 编排 | LLM 生成 Python | 固定并发 runner | manager/builder/executor |
| 持久化 | WorkflowEventStore | resume_compact | checkpoint |

---

## 关键设计决策

1. **动态类型发现**：`_build_available_types_hint(catalog)` 与 delegate 看到相同 agent_type 列表
2. **Cancel 传播**：每阶段边界 + 每次 spawn 检查 `cancel_token`
3. **Readonly 模式**：`disallowed_tools` + `WorkspacePolicy.READ_ONLY_SANDBOX`
4. **汇总层**：原始 stdout 经 SUMMARIZATION_PROMPT 转为 Markdown + 置信度前缀

---

## 扩展指南

1. 新 PTC 工具 → `tools.py` + ORCHESTRATOR_PROMPT 文档
2. 存储变更 → 保持 workflow_id 确定性
3. 更新 [dynamic_workflow/_ARCH.md](_ARCH.md)

---

## 参考资料

- [dynamic_workflow/_ARCH.md](_ARCH.md)
- [SUB_AGENT_SYSTEM.md](../sub_agents/SUB_AGENT_SYSTEM.md)
