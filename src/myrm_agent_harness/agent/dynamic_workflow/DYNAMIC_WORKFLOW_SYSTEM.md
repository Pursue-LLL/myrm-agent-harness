# Dynamic Workflow System Design

> **DW PTC** 编排层（PTC 家族 SSOT：[EXECUTION_SYSTEM.md](../../toolkits/code_execution/EXECUTION_SYSTEM.md) § PTC 家族）。LLM 生成 Python 编排脚本，在 DW PTC 沙箱中并发 spawn 子 Agent，突破单 Agent 上下文限制。

---

## 设计目标

1. **Code-as-Orchestrator**：循环/分支/并行逻辑交给 Python，保持 orchestrator LLM 上下文干净
2. **与 delegate 同路径**：`SpawnSubagentTool` → `spawn_prep.py` → `parent_agent._spawn_child()`，工具/registry/预算与 `delegate_task_tool` 一致
3. **Durable 执行**：SQLite Event Store + `SpawnCacheParams` 指纹；参数不变 replay，参数变则重跑
4. **SSE 兼容**：标准 `AgentEventType`（message/message_end/status），前端无需新类型

---

## 系统架构

```
Server (use_workflow=True | workflow_template_id set)
       ↓
run_dynamic_workflow_stream (__init__.py)
       ↓
[optional] WorkflowTemplateStore — pinned template load + template_args substitution
       ↓
LLM → Python 编排脚本 (ORCHESTRATOR_PROMPT + SubagentCatalog hint)   ← skipped when pinned
       ↓
preflight.py — 静态 spawn 计数 + `_estimate_batch_cost` + HITL plan_confirm (trust_latch may skip)
       ↓
orchestration_scripts persist (per-run + save-from-run source)
       ↓
PTC Sandbox (DW PTC · WorkflowRunGuard: max 50 spawns, concurrency 5)
       ↓
SpawnSubagentTool / NotifyProgressTool (tools.py)
       ↓
spawn_prep.py (shared with delegate) — readonly / memory / ISOLATED_COPY
       ↓
notify_stream.py — 并发 drain queue，PTC 执行期间实时 yield workflow_stage
       ↓
WorkflowEventStore (store.py) — L2 cache / replay（spawn_params_json 指纹）
       ↓
batch_merge (workspace_coordination) — 非 readonly spawn 执行后合并 workspace
       ↓
Summarization LLM → 用户可读 Markdown
```

---

## 核心文件

| 文件 | 职责 |
|------|------|
| `__init__.py` | `run_dynamic_workflow_stream` 入口；脚本生成；approval_gate 注入；PTC 执行；汇总 |
| `preflight.py` | 静态 spawn 分析；费用预估；`WorkflowPlanReview` / `WorkflowApprovalGate` |
| `notify_stream.py` | PTC 执行期间并发 drain notify queue |
| `store.py` | SQLite Event Sourcing；`SpawnCacheParams` 指纹 cache + orchestration script 持久化 |
| `template_store.py` | 用户命名模板库 `workflow_templates`；save-from-run；pinned rerun 加载 |
| `template_validation.py` | 模板脚本校验、占位符替换、trust_latch plan_confirm 跳过护栏 |
| `paths.py` | `{harness_root}/.myrm/workflow_events.db` 路径 SSOT（与 background_jobs 同根） |
| `spawn_cache.py` | `SpawnCacheParams` / fingerprint SSOT |
| `tools.py` | `SpawnSubagentTool`（WorkflowRunGuard、cache 指纹、非 readonly ISOLATED_COPY、adversarial verify）/ `NotifyProgressTool` |

---

## 与 sub_agents / parallel 边界

| | dynamic_workflow | parallel | sub_agents |
|--|------------------|----------|------------|
| 触发 | Server workflow 模式 | batch_delegate / swarm | 通用委派全栈 |
| 编排 | LLM 生成 Python | 固定并发 runner | manager/builder/executor |
| 持久化 | WorkflowEventStore | resume_compact | checkpoint |

### DW PTC Runtime Tools（不计入 LLM 71）

| 名称 | 暴露名 | 职责 | 与 LLM 工具关系 |
|------|--------|------|----------------|
| `SpawnSubagentTool` | `myrm_tools.spawn_subagent()` | PTC 脚本内阻塞 spawn；可选 `verification_mode=adversarial` → `run_with_verification` | 下游同 `_spawn_child()` / verify 路径；≠ LLM `delegate_task_tool` |
| `NotifyProgressTool` | `myrm_tools.notify()` | PTC 脚本阶段进度 → SSE `workflow_stage` | 零 Turn1 bind |

登记：`scripts/tool_registry_config.py` `PTC_RUNTIME_TOOL_NAMES`。完整分类见 [TOOL_MANAGEMENT_SYSTEM.md](../tool_management/TOOL_MANAGEMENT_SYSTEM.md) §内部分类。

---

## 关键设计决策

1. **动态类型发现**：`_build_available_types_hint(catalog)` 与 delegate 看到相同 agent_type 列表
2. **Cancel 传播**：每阶段边界 + 每次 spawn 检查 `cancel_token`
3. **Readonly 模式**：`disallowed_tools` + `WorkspacePolicy.READ_ONLY_SANDBOX`
4. **Named Template Library (vMIN)**：用户将成功的 DW 编排脚本保存为命名模板；后续 run 通过 `workflow_template_id` 跳过 orchestrator LLM，仅替换 `{placeholder}` 参数（Settings 库页条件表单 + summary `placeholders[]`）。`trust_latch` + 全 readonly spawn + 低成本时可跳过 plan_confirm。Server 暴露 `/workflow-templates` CRUD + `from-run`；WebUI Save CTA + Settings → Workflow Templates（只读 script 预览）；Cron job 可选绑定 `workflow_template_id`（unattended 自动 plan approve）。
5. **汇总层**：原始 stdout 经 SUMMARIZATION_PROMPT 转为 Markdown + 置信度前缀
6. **Trust 层**：spawn ≥ 1 时 SSE `plan_confirm`（literal spawn 数 + 运行时 hard cap 文案）+ PhaseWaiter；RunGuard 硬上限 50 spawn / 5 并发
7. **Workspace 安全**：DW 非 readonly spawn 使用 `ISOLATED_COPY`；defer 时 child workspace 保留至 `batch_merge`；merge 后 sanitize 存 SQLite（`workspace_merge_status=merged`）；merge 经 `build_merge_snapshot_context` 登记 SnapshotStore（Revert 可用）并在摘要 append `_workspace_diff`；merge 失败时 SSE `workflow_execution: warning`、`WORKSPACE_MERGE_FAILED` 与 `completion_status: warning`，前端 `WorkspaceMergeWarning` 展示逐条错误
8. **Spawn prep SSOT**：`agent/sub_agents/spawn_prep.py` 与 delegate 共用
9. **Durable replay**：`SpawnCacheParams` 指纹命中复用 spawn 结果；`workspace_merge_status=merged` 跳过 re-spawn/re-merge；`pending` 行视为 incomplete 强制 re-spawn

---

## 扩展指南

1. 新 PTC 工具 → `tools.py` + ORCHESTRATOR_PROMPT 文档
2. 存储变更 → 保持 workflow_id 确定性
3. 更新 [dynamic_workflow/_ARCH.md](_ARCH.md)

---

## 参考资料

- [dynamic_workflow/_ARCH.md](_ARCH.md)
- [SUB_AGENT_SYSTEM.md](../sub_agents/SUB_AGENT_SYSTEM.md)
