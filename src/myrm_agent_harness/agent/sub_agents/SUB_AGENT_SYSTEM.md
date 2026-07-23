# Sub-Agent System Design

> Subagent 生命周期管理系统。提供受控委派、工具隔离、预算治理、检查点恢复和事件转发能力。

---

## 设计目标

1. **安全隔离**：子 agent 的工具访问受四层安全约束（L0 类型准入 + L1 全局黑名单 + L2 per-config + L3 父子交集），防止权限逃逸。子 agent 的 taint labels 自动传播到父 agent 的 taint_tracker，防止跨 agent 注入攻击链
2. **资源可控**：Token 预算、并发上限、嵌套深度、每节点子任务数、每运行树总后代数均可声明式配置
3. **Token 精确追踪**：子 agent 用量从 `last_run_stats` 精确合并到父 tracker
4. **层级解耦**：与 BaseAgent、progress 中间件、Goal 系统通过明确接口协作
5. **声明式配置**：一个 `SubagentConfig` dataclass 描述子 agent 的全部行为

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                      BaseAgent (父 agent)                      │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ SubagentManager                                        │  │
│  │  - _children: dict[task_id, asyncio.Task]              │  │
│  │  - _children_types: dict[task_id, agent_type]          │  │
│  │  - _children_results: dict[task_id, SubAgentResult]    │  │
│  │  - _semaphore: asyncio.Semaphore(5)                    │  │
│  │  - _current_depth: int                                 │  │
│  │  - _budget_state: DelegationBudgetState                │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  LLM 工具集:                                                  │
│  ├── delegate_task_tool (mode=single|batch|parallel)          │
│  ├── subagent_control_tool (action=list|cancel|steer)       │
│  └── send_teammate_message_tool (orchestrator P2P)            │
└──────────────────────────────────────────────────────────────┘
         │ spawn_child()          │ cancel_all()
         ▼                        ▼
┌──────────────────┐  ┌──────────────────┐
│  Child Agent A   │  │  Child Agent B   │
│  (asyncio.Task)  │  │  (asyncio.Task)  │
│  独立 TokenTracker│  │  独立 TokenTracker│
│  过滤后工具集    │  │  过滤后工具集    │
└──────────────────┘  └──────────────────┘
```

### 文件分布

| 文件 | 职责 |
|:--|:--|
| `agent/sub_agents/types.py` | SubagentConfig（含 agent_factory/role/budget）, AgentFactory Protocol, SubAgentStatus, SubAgentResult, SubagentCatalog Protocol, DelegationCapabilityManifest 能力清单 |
| `agent/sub_agents/budget.py` | 委派运行树预算计数（max_descendants_per_run），防止递归/批量委派暴走 |
| `agent/sub_agents/builder.py` | 子 agent 构建（async build_child_agent 支持 AgentFactory 委托、工具过滤、模型解析、结果截断、Token 合并） |
| `agent/sub_agents/manager.py` | 核心执行器（spawn/cancel/wait/chain/merge + checkpoint save/resume） |
| `agent/sub_agents/checkpoint/saver.py` | 检查点保存/恢复（SubagentCheckpoint, SubagentCheckpointStorage, JSON后端） |
| `agent/sub_agents/checkpoint/state_extractor.py` | 状态提取工具（extract_subagent_state_sync/async，从child agent提取context/stats/messages） |
| `agent/sub_agents/config_loader.py` | YAML 配置加载器（SubagentConfigLoader, Pydantic 验证, 批量目录加载） |
| `agent/graceful_shutdown.py` | 优雅关机管理器（GracefulShutdownManager，SIGTERM/SIGINT信号处理，单例模式） |
| `agent/base_agent.py` | 委托入口 + `_last_context` 保存 + 父取消传播 |
| `agent/meta_tools/spawn_subagent/delegate_task_tool.py` | LLM `delegate_task_tool`（mode=single|batch|parallel；动态 roster + session 缓存 + 预算并发） |
| `agent/meta_tools/spawn_subagent/agent_manage_tool.py` | LLM `subagent_control_tool`（list/cancel/steer） |
| `agent/meta_tools/spawn_subagent/delegation_pause_gate.py` | Session 级委派暂停门闩（REST + tool 入口） |
| `agent/dynamic_workflow/tools.py` | PTC `spawn_subagent` / `notify`（`use_workflow=True`；不进 `_TOOL_LAYERS`；下游同 `_spawn_child()`） |
| `sub_agents/dag_plan.py` | Orchestrator DAG 内部 Plan/PlanStep 类型（非用户面工具） |
| `configs/subagents/` | 外部 YAML 配置文件（core 核心配置 + custom 自定义配置） |

### 6 个核心抽象

| 抽象 | 职责 | 关键字段 |
|:--|:--|:--|
| **SubagentConfig** | "是什么" — 声明式配置 | tools, disallowed_tools, model, llm, budget_tokens, max_spawn_depth, max_children_per_agent, max_descendants_per_run, max_batch_size, agent_factory, model_resolver, display_name, memory_isolation_policy, control_scope, delegation_role, workspace_policy |
| **AgentFactory** | "谁来构建" — 业务层注入的 Agent 构建协议 | build(config, tools, task_description, parent_agent, current_depth, complexity_tier) → BaseAgent |
| **ModelResolver** | "用什么模型" — 业务层注入的 model→LLM 解析协议 | resolve(model_name, complexity_tier, task_description) → BaseChatModel |
| **SubAgentResult** | "结果是什么" — 结构化输出 | success, result, token_usage, duration, completed_at, status, accumulated_duration_seconds |
| **SubagentManager** | "怎么做" — 执行器 + 编排 | spawn_child, execute_batch_delegation, run_alternatives, run_chain, run_with_verification, cancel_all, wait_children(timeout) |
| **SubAgentStatus** | "做到哪了" — 状态枚举 | PENDING, RUNNING, VERIFYING, COMPLETED, FAILED, TIMED_OUT, CANCELLED, CANCELLED_BY_BUDGET, PENDING_APPROVAL, YIELDED, INTERRUPTED |
| **DelegationCapabilityManifest** | "能注入/能剥离什么" — 委派工具能力清单 | leaf_blocked_tools, orchestrator_child_tools, privileged_skill_tools |

---

## 核心组件说明

### 1. 五层工具安全隔离

```
Layer 0: create_delegate_task_tool(allowed_types=...)
         → 类型准入控制，限制可委托的 agent 类型

Layer 1: DELEGATION_CAPABILITY_MANIFEST.leaf_blocked_tools
         → delegate_task_tool + subagent_control_tool + skill_manage/discovery_tool
           + ask_question_tool (HITL must stay on parent/web thread);
           同一份 manifest 同时驱动 leaf 剥离和 orchestrator child-scoped 工具注入

Layer 2: SubagentConfig
         → tools (白名单) + disallowed_tools (黑名单)

Layer 3: child ⊆ parent 交集约束
         → 子 agent 工具集 ⊆ 父 agent 工具集

Layer 4: Fine-grained Sandboxing (readonly)
         → 支持通过 readonly 参数在运行时过滤文件写/命令执行等具有副作用的工具，实现细粒度安全沙箱。
```

### 1.1 安全策略（SubagentConfig 声明式）

| 策略 | 枚举 | 值 | 说明 |
|:--|:--|:--|:--|
| **ControlScope** | `LEAF` | 叶子节点 | 默认，禁止再次委托，强制 max_spawn_depth=0 |
|  | `ORCHESTRATOR` | 受控协调者 | 仅可信配置可用；必须显式通过 `role="orchestrator"` 请求，运行时注入 child-scoped `delegate_task_tool` + `subagent_control_tool` + `send_teammate_message_tool` |
| **MemoryIsolationPolicy** | `EPHEMERAL_SESSION` | 临时会话 | 默认，独立记忆空间 |
|  | `READ_ONLY_GLOBAL` | 只读全局 | 阻止 memory write tools（memory_save/memory_manage_tool） |
| **WorkspacePolicy** | `INHERIT` | 继承 | 默认，共享父工作空间 |
|  | `ISOLATED_COPY` | 隔离副本 | `shutil.copytree` COW 克隆工作空间 + `_sync_tree` 完美镜像同步 |

### 2. Token 用量追踪与预算

**实时预算检查**：在 `async for event in child_agent.run()` 循环中，从 `TOKEN_USAGE` 事件
提取累积 `total_tokens`，与 `config.budget_tokens` 比较，超限时立即 break。
这确保预算检查在流式执行过程中实时生效，而非等到 generator 完成后。

**委派树预算检查**：`DelegationBudgetState` 在 root run 内共享，`spawn_child()` 先预留
一个后代额度，再创建 asyncio task。`max_children_per_agent` 限制单节点同时运行子任务数，
`max_descendants_per_run` 限制整棵委派树累计后代数；`delegate_task_tool` 的 `mode=batch` 受单次批量规模约束。
预算拒绝返回结构化 `payload.reason="budget_exceeded"`，便于上层 UI 和日志解释。

**完成后精确合并**：子 agent 完成后，从 `child_agent.last_run_stats` 获取
最终 token 用量，通过 `_merge_child_stats()` 精确合并到父 tracker。

合并内容：
- 7 种 token 类型（prompt/completion/total/cached/cache_write/reasoning/citation）
- 模型级用量和费用（model_usage + model_cost）
- 总费用和费用状态（total_cost_usd + cost_status）

**Race 模式预算准入**：`delegate_task_tool(mode=batch, race=True)` 使用结构化成本准入。
它优先汇总各任务 `SubagentConfig.max_cost_usd`，否则基于 `budget_tokens + model`
调用 token cost engine 估算；无法得到可信成本时返回 `budget_admission.status="unavailable"`，
预算不足或预算守卫进入 finalization/exceeded 时自动降级为顺序执行并携带结构化原因。

### 3. Context 自动继承

`_inherit_parent_context()` 自动从父 agent 的 `_last_context` 和执行时环境提取继承关键字段：
- `session_id` — `base_agent._setup_workspace()` 必需
- `WorkspaceBinding` — 沙箱文件系统隔离的核心，子 agent 从 parent context 精准继承，确保二者操作同一个物理工作空间（但独立运行）。
- `approval_session_key` — HITL 审批必需

**Fork 模式上下文过滤**（`context_mode="fork"`）：

通过 `_filter_fork_messages()` 实现结论性过滤，子 agent 仅继承父 agent 的结论性上下文：
- **保留**：SystemMessage、HumanMessage、有 content 的 AIMessage（剥离 tool_calls 元数据）
- **丢弃**：ToolMessage、纯 tool_calls 无 content 的 AIMessage
- **截断**：`max_fork_tokens` 超预算时从最旧消息开始裁剪（保留 SystemMessage）

配合 builder.py 的 `system_prompt = ""` 设计，子 agent 复用父 SystemMessage 实现 100% Prefix Cache Hit。

### 4. 模型解析链（4 级）

```
Level 1: config.llm (预构建 LLM 实例)
Level 2: config.model + config.model_resolver (名称字符串 → ModelResolver 解析为 LLM，支持 complexity_tier 智能路由)
Level 3: config.model 无 resolver (仅日志记录，fallthrough)
Level 4: parent LLM (继承父 agent 的 LLM，兜底)
```

业务层通过 `LLMManager.get_llm_from_config()` 预创建 LLM 实例设置到 `config.llm`，
或通过注入 `ModelResolver` 使框架层可根据 model 名称字符串解析为 LLM 实例。
框架层不直接访问 API key 等配置，保持层级解耦。

### 5. 编排模式

| 模式 | API | 用法 |
|:--|:--|:--|
| 同步 | `spawn_child(wait=True)` | 等待子 agent 完成后返回结果 |
| 异步 | `spawn_child(wait=False)` + `wait_children()` | 启动子任务返回 Task ID，可随时查询结果 |
| 并行批量 | `delegate_task_tool(mode=batch)` | `asyncio.gather` 并行执行多个子任务（`max_concurrent` 可调并发度，race 模式 Speculative Execution first-winner） |
| 链式 | `run_chain(configs)` | A → B → C，`{previous}` 模板传递 |
| 替代方案 | `run_alternatives(task, configs)` | 并行派发 N 个子 agent 执行相同任务（各自 ISOLATED_COPY 隔离工作区），收集全部结果但不自动合并。上层按需调用选中结果的 `_workspace_sync_back` 合并工作区 |
| 验证式 | `run_with_verification(worker, verifier, ...)` | Worker → Verifier 对抗验证，FAIL 则注入反馈重试，最多 max_rounds 轮。支持 `WorkspacePolicy.READ_ONLY_SANDBOX` 模式，通过 `ReadonlyExecutorProxy` 强制 Verifier 必须执行代码验证，防止 LLM 幻觉。 |

### 5.1 Worker / Coordinator 运行时角色

`ControlScope` 是可信配置上限，`DelegateRole` 是本次委派请求的运行时角色。
默认 `role="leaf"` 会把子 agent 收敛为 Worker，并移除再次委派能力；只有当 catalog
配置为 `ControlScope.ORCHESTRATOR` 且请求显式使用 `role="orchestrator"` 时，Executor
才会在子 agent 上重新绑定 child-scoped `delegate_task_tool` + `subagent_control_tool` + `send_teammate_message_tool`
工具。注入列表来自 `DelegationCapabilityManifest.orchestrator_child_tools`，与 leaf 黑名单
保持同源。这样 Coordinator 只能控制自己的子树，不能观察或干预兄弟任务。

### 6. Force-Stop Checkpoint Save（自动中断恢复）

**核心能力**：进程收到 SIGTERM/SIGINT 时自动保存所有运行中子Agent状态，支持后续恢复执行。

**架构组件**：
- `GracefulShutdownManager`：单例模式，自动注册SIGTERM/SIGINT信号处理器
- `SubagentCheckpointStorage`：轻量级JSON文件后端（默认 `{MYRM_DATA_DIR}/checkpoints/`，未设置时回退 `.myrm/checkpoints/`）
- `BaseAgent.get_checkpoint_state()`：✅ 统一API接口，异步提取完整状态（messages+context+stats）
- `checkpoint/state_extractor.py`：状态提取工具（extract_subagent_state_sync/async，复用BaseAgent API）

**状态提取策略**：
1. **同步提取**（signal handler context，技术限制）：
   - `_last_context`：运行时上下文（session_id、workspace_path等）
   - `last_run_stats`：token usage、duration、status
   - ⚠️ messages为空（signal handler无法await异步checkpointer）
2. **异步提取**（BaseAgent.get_checkpoint_state()）：
   - ✅ LangGraph checkpointer：完整messages历史
   - ✅ last_tool：最后执行的工具名
   - ✅ 统一API接口，复用BaseAgent逻辑

**Resume流程**：
```python
# 1. 从checkpoint恢复context
checkpoint = await storage.load(task_id)
# 2. 恢复runtime variables
restored_context = checkpoint.variables
# 3. 返回checkpoint_data给业务层，业务层可用messages创建新session
result = SubAgentResult(checkpoint_data={...})
```

**零侵入设计**：SubagentManager初始化时自动注册shutdown callback，用户无需修改代码。

**REST API**：4个端点（list/resume/delete/cleanup）暴露checkpoint管理能力。

**完整实现（10/10）**：
- ✅ BaseAgent.get_checkpoint_state()统一API（异步提取messages+context+stats）
- ✅ **异步checkpoint save**（asyncio.run()在signal handler中，完整提取messages）
- ✅ **CheckpointMetrics**监控数据结构（save/resume成功率、平均耗时、.to_dict()导出）
- ✅ **Resume返回完整checkpoint_data**（包括messages、variables、progress、last_tool）
- ✅ 业务层可灵活使用messages创建新agent session

**设计理念**：
框架提供数据结构和导出能力，业务层决定如何使用，符合FRAMEWORK_DESIGN_PRINCIPLES.md：
- CheckpointMetrics：框架track，业务层monitoring
- checkpoint_data：框架返回，业务层创建session

**部署架构适配（Agent in Sandbox）**：
- ✅ 每个用户一个独立沙箱容器（如Fly.io）
- ✅ 容器挂载持久化Volume（EBS/Fly Volume）
- ✅ 用户数据（`{MYRM_DATA_DIR}/checkpoints/`，生产由 server 注入 `MYRM_DATA_DIR`）存储在 Volume 中
- ✅ 容器重启后数据保留
- ✅ **JSON backend完全满足需求**（无需S3/Redis分布式存储）
- ✅ SaaS多租户场景：每个用户独立Volume（天然隔离）

### 7. Checkpointer 隔离

子 agent 不继承父 agent 的 checkpointer（设为 None）。原因：
- 子 agent 是短命的，不需要持久化状态
- 共享 checkpointer 会导致子 agent 的消息历史写入父 agent 的 checkpoint thread，造成状态污染
- 子 agent 不支持也不需要 HITL interrupt

### 8. 状态追踪与自动清理

- 10 种状态：PENDING → RUNNING → VERIFYING → COMPLETED / FAILED / TIMED_OUT / CANCELLED / CANCELLED_BY_BUDGET / PENDING_APPROVAL / YIELDED
- `_cleanup_child` 回调在 `asyncio.Task` 完成时自动触发
- `_children_types` 映射保证状态记录中 `agent_type` 准确
- 超过 50 条完成记录时按 `completed_at` FIFO 清理最旧条目
- `SubAgentResult.completed_at` 精确记录完成时间戳（`to_dict()` 在 `still_running=True` 时省略此字段）

### 9. 进度与日志事件（自动透明度）

**事件类型**：
- `SUBAGENT_START` — 子 agent 开始执行
- `SUBAGENT_PROGRESS` — 执行进度更新（**自动**）
- `SUBAGENT_LOG` — 工具调用日志（**自动**）
- `SUBAGENT_COMPLETION` — 子 agent 完成（push通知）
- `SubagentLifecycleEvent(policy_denied)` — 委派策略拒绝（role 提权 / 深度耗尽），携带 `DelegationPolicyDecision`

**自动机制**（框架内置，零侵入）：

`SubagentManager` 在 event loop 中自动监听子 agent 事件并转发：

1. **自动进度计算**：
   - 监听 `TOKEN_USAGE` 事件
   - 有预算时：`progress = current_tokens / budget_tokens`
   - 无预算时：`progress = tool_count / 8`（基于工具调用次数估算）
   - 节流机制：progress变化>=5%或时间间隔>=1s才发送（避免事件洪流）
   - 追踪当前步骤：在`TOOL_START`时更新`current_tool_name`，显示具体工具名
   - 自动发送 `SUBAGENT_PROGRESS` 事件，包含 `is_estimated`、`tool_count`、`current_step` 字段
   - 显示："正在搜索...30%"

2. **自动日志转发**：
   - 监听 `TOOL_START` / `TOOL_END` / `TOOL_FAILURE` 事件
   - 自动发送 `SUBAGENT_LOG` 事件
   - 成功：显示"Calling tool: web_search" → "Tool completed: web_search (3200ms)"
   - 失败：显示"Tool failed: web_search - Connection timeout"（level=ERROR）

**优势**：
- ✅ 零侵入：不需修改任何子 agent 代码
- ✅ 自动生效：所有子 agent 自动获得进度和日志
- ✅ 真实进度：基于 token 消耗，不是假心跳
- ✅ 详细日志：追踪每个工具调用
- ✅ ETA估算：基于token消耗速率计算剩余时间
- ✅ 可扩展：支持自定义ProgressCalculator Protocol

**前端展示**：
- `SUBAGENT_PROGRESS` → 进度条 + **running `token_usage`**（节流 1s，与 progress 同 emit；Dashboard 树节点实时显示 tok）
- `SUBAGENT_LOG` → 实时日志流："Calling tool: web_search" → "Tool completed"
- `SUBAGENT_START`/`subagents_updated` → Subagent Dashboard 展示 role、control_scope、budget、effective_model 和 policy denial reason
- `subagent_status_update` → completed 节点 final `token_usage`
- Settings `AgentSubagentBinding` → 修改 `subagent_ids` 后 inline rebind 提示（需新开对话）

### 10. 结果缓存 Session 隔离

`delegate_task_tool` 的结果缓存键包含 `session_id`，防止 Sandbox 模式下跨用户缓存污染。

### 11. 非致命超时 (Non-fatal Timeout)

`spawn_child(wait=True)` 和 `wait_children(timeout=...)` 均采用**非致命超时**：

- **等待超时 (wait timeout)**：`config.timeout_seconds`，超时后返回 `SubAgentResult(status=TIMED_OUT, still_running=True)`，子 agent **继续后台运行**，不做 cancel。
- **硬安全超时 (hard safety timeout)**：`config.timeout_seconds * 3`，作为最终安全网终止真正的 runaway agent。
- **LLM 决策权**：超时后 Parent Agent 可选择等待（`subagent_control_tool action=list`）、做别的事、或主动 cancel。
- **`still_running` 字段**：`SubAgentResult.still_running: bool` 为 True 表示 agent 仍在后台运行。

现有安全保障：budget_tokens / max_cost_usd / max_turns / `subagent_control_tool action=cancel` 均不受影响。

### 12. Chain 错误上下文

`run_chain` 失败时，错误信息包含 `[chain step N/M (agent_type)]` 前缀，
提供失败步骤索引和总步数，便于定位失败环节。

### 13. 配置外部化

Subagent 配置通过 YAML 文件管理，支持声明式定义和自动加载：

配置目录结构：
```
configs/subagents/
  ├── core/       # 框架提供的核心配置
  └── custom/     # 用户自定义配置（优先级高于 core）
```

配置加载：
- `SubagentConfigLoader` 提供 Pydantic 验证 + Action Tool SSOT 校验（`tools`/`disallowed_tools` 必须在 `tool_layers._TOOL_LAYERS` 注册）
- 安全特性：文件大小限制、工具名称正则验证、system_prompt 长度限制
- 错误处理：单文件加载失败跳过该文件；`filter_tools` 后 allowlist 为空则子 Agent 立即 `FAILED`（不空跑）

内置 preset 工具名必须与 `@tool()` 注册名一致（SSOT：`tool_layers.py`）。例如 browser preset 使用 `browser_interact_tool`，analysis preset 使用 `memory_search_tool`。

当 Agent 启用 browser 内置工具时，server 层在 `AgentFactory.create_general_agent` 自动 peripheral 绑定 prebuilt `browser-automation` skill（`is_core:false`，不占 Turn1 schema）。

优势：
- 扩展新 subagent 类型无需修改代码
- 配置文件独立版本控制
- 降低技术门槛（YAML vs Python）
- 配置变更无需修改 Python 代码

### 14. 生命周期 Hook

```python
SubAgentHook(
    on_spawn=async_fn,    # 子 agent 创建时
    on_complete=async_fn, # 子 agent 成功完成时
    on_error=async_fn,    # 子 agent 失败时
)
```

Hook 异常不影响主流程（catch + warning 日志）。

---

## 能力矩阵

| 维度 | 当前实现 |
|:--|:--|
| 工具安全 | 类型准入、DelegationCapabilityManifest 同源能力清单、per-config allow/block list、父子工具交集和 readonly 沙箱 |
| 运行时角色 | `ControlScope` 限定可信上限，`DelegateRole` 控制 leaf/orchestrator 运行时行为 |
| 委派入口隔离 | leaf 子 agent 剥离 `delegate_task_tool`、`subagent_control_tool` 和技能管理工具；orchestrator 只注入 child-scoped 委派/控制/队友工具 |
| 预算治理 | token、单节点子任务数、全树后代数、批量规模、race 成本准入和全局深度上限 |
| 批处理语义 | `delegate_task_tool(mode=batch)` 返回 completed / partial_success / failed、成功/失败计数和 failure_reasons |
| 策略可观测性 | `DelegationPolicyDecision` + typed SubagentLifecycleEvent 透传 role/control_scope/policy reason |
| Token 合并 | 从 `last_run_stats` 精确合并子 agent token、模型用量和费用 |
| 取消机制 | 支持 immediate、graceful、checkpoint 三种取消策略和父级传播 |
| 结果压缩 | `max_result_tokens` 限制子任务返回给父任务的上下文体积 |
| Context 继承 | 自动继承 `session_id`、`WorkspaceBinding`、审批会话等运行上下文 |
| Fork 上下文过滤 | `context_mode="fork"` 结论性过滤（`_filter_fork_messages`）：保留 System/Human/AI 结论，剥离 ToolMessage 和 tool_calls，`max_fork_tokens` 预算截断 |
| 模型解析 | 支持 config LLM、ModelResolver、父 agent LLM 的分层解析 |
| 缓存隔离 | delegate 结果缓存键包含 `session_id`，避免跨会话污染 |
| 非致命超时 | `spawn_child(wait=True)` / `wait_children()` 超时后不 cancel，子 agent 继续后台运行（`still_running=True`） |
| Chain 可调试性 | 链式编排错误包含 step index/total |
| 配置管理 | YAML 配置加载、Pydantic 校验和注册表优先级 |
| 自动进度与日志 | 子 agent 事件转发为统一的进度和日志事件 |
| 失败 partial 回传 | MyrmLLMError / BudgetExceeded / generic Exception 三条失败路径均返回结构化 `SubAgentResult(result=partial_output)`，截断保护防 context 爆炸，统一触发 `SUBAGENT_STOP` hook |

### 15. Cooperative Subagent Cancellation

**设计目标**：提供灵活的子 agent 取消策略，支持立即取消和优雅退出，确保资源正确管理。

**取消策略（CancellationStrategy）**：

| 策略 | 行为 | 适用场景 |
|:--|:--|:--|
| **IMMEDIATE** | 强制立即取消（asyncio.Task.cancel()） | 需要快速终止的任务 |
| **GRACEFUL** | 等待当前工具调用完成后优雅退出（设置cancel_flag） | 默认策略，适合大多数场景 |
| **CHECKPOINT** | 保存中间状态后取消（适用于可恢复任务） | 长时间运行的可恢复任务 |

**实现机制**：

1. **Cancel Flag**：
   - `SubagentManager._cancel_flags: dict[str, bool]` 存储每个子 agent 的取消标志
   - `cancel_child()` 根据 `cancellation_strategy` 决定行为：
     - `IMMEDIATE`：直接调用 `task.cancel()`
     - `GRACEFUL/CHECKPOINT`：设置 `_cancel_flags[task_id] = True`

2. **优雅退出**：
   - 在 `_run_single_attempt` 的 event loop 中检查 cancel_flag
   - 检测到 cancel_flag 后，触发 `SUBAGENT_CANCEL_START` 钩子
   - 抛出 `asyncio.CancelledError` 优雅退出

3. **资源清理**：
   - `_run_subagent_core` 使用 try-finally 块确保资源清理
   - finally 块中清除 cancel_flag 并触发后代级联取消
   - 即使取消或异常也能保证资源释放

4. **生命周期钩子**：
   - `SUBAGENT_CANCEL_START`：开始取消时触发
   - `SUBAGENT_CANCEL_COMPLETE`：取消完成时触发

**配置示例**：

```python
config = SubagentConfig(
    system_prompt="...",
    tools=(...),
    cancellation_strategy=CancellationStrategy.GRACEFUL,  # 默认
    graceful_cancel_timeout_seconds=5.0,  # 超时后强制取消，默认5秒
)
```

5. **级联取消（Cascade Cancel）**：
   - **第一层**（executor）：`executor.py` 的 CancelledError 处理中调用 `_cascade_cancel_descendants()` — 覆盖 IMMEDIATE 取消场景
   - **第二层**（manager 安全网）：`manager.py:_run_subagent_core` 的 finally 块调用 `child.cancel_all_children()` — 覆盖 GRACEFUL/CHECKPOINT 主动退出及所有异常退出路径
   - 防止多层 orchestrator 场景（A→B→C）中取消 B 后孙级 C 继续运行消耗 token
   - 受 `max_spawn_depth` 硬性深度限制保护，不需要额外防环机制

**优势**：
- ✅ 灵活：支持三种取消策略，满足不同场景
- ✅ 安全：确保资源正确释放，防止内存泄漏 + 超时保护防止无限等待
- ✅ 优雅：GRACEFUL策略等待当前工具完成，避免状态不一致
- ✅ 可观测：提供取消生命周期钩子，支持自定义逻辑
- ✅ 完整：级联取消确保多层嵌套场景下所有后代任务被正确终止

### 16. Active Context Injection（活跃子Agent上下文注入）

**设计目标**：防止长对话上下文压缩后 LLM 丢失运行中子Agent信息，导致重复 spawn 浪费 token。

**核心机制**：
1. 每轮 LLM 推理前，从 `SubagentManager.list_children()` 筛选 `status=running` 的子Agent
2. 通过 `format_active_subagent_context()` 格式化为简洁摘要（包含 task_id、agent_type、description）
3. 作为 HumanMessage 追加到消息末尾（与 drain_notifications 一致，保护 Prompt Cache）
4. 包含反重复 spawn 指导语，引导 LLM 使用 `subagent_control_tool action=list` 查询结果

**触发条件**：仅当有活跃（running）子Agent时注入，无活跃子Agent时零开销。

**与 drain_notifications 的关系**：
- `drain_notifications`：已完成子Agent的结果通知（一次性消费）
- `format_active_subagent_context`：当前运行中子Agent的状态快照（每轮刷新）
- 两者互补，共同确保 LLM 对子Agent全生命周期的感知

**优势**：
- ✅ ~20行代码，复用现有 list_children() 数据
- ✅ HumanMessage 注入，不破坏 Prompt Cache
- ✅ 条件触发，无活跃子Agent时零 token 开销
- ✅ 比 OpenClaw 更优（更简洁、更精确、缓存友好）

### 17. 空闲唤醒与异步事件注入（Idle Wakeup & Event-Driven Continuation）

**设计目标**：让大模型在派发长耗时后台任务时通过事件唤醒恢复推理，避免依赖循环轮询查询状态。

**核心机制**：
1. **状态挂起**：当大模型派发任务 `wait=False` 时，主智能体进入 Idle（空闲）状态，停止消耗 Token，挂起释放资源。
2. **异步回调拦截**：后台子代理完成任务后，`SubagentManager._cleanup_child` 捕获到完成事件。
3. **事件反转注入**：通过 `self._parent_agent.trigger_async_wakeup(result)` 向主智能体所在的 Session 注入一条系统事件 `ASYNC_WAKEUP`。
4. **重新唤醒**：业务层（`myrm-agent-server/app/services/agent/wakeup_handler.py`）收到 `ASYNC_WAKEUP` 后，将子任务结果包在 `<system_notification type='async_result'>` 中追加为 **user/HumanMessage**（写入 chat history），再触发 headless GeneralAgent 续跑。不使用 `SystemMessage`，避免破坏 System 前缀 cache。

**优势**：
- ✅ **异步并发**：主 agent 可挂起长耗时子任务并等待事件唤醒。
- ✅ **事件恢复**：通过事件注入恢复推理，避免主 agent 周期性查询子任务状态。

### 18. 并发漏桶防爆队列（TokenBucket Scheduler）

**设计目标**：降低多 Agent 并发派发子任务时触发大模型厂商 API 速率限制（HTTP 429）或本地显存耗尽（OOM）的风险。

**核心机制**：
- 在 `ChatLiteLLM` 的网络请求网关处，引入 `_GLOBAL_SEMAPHORE` (基于 `LLM_GLOBAL_MAX_CONCURRENCY` 环境变量)。
- 主 Agent 和并发子 Agent 在发起实际的 LLM 推理请求时，都必须获取双重锁（全局漏桶锁 + 模型特定锁）。

**优势**：
- ✅ **并发削峰**：高并发请求转化为排队等待，降低瞬时超限风险。
- ✅ **资源可控**：通过全局和模型级信号量约束并发推理请求。

### 19. Server registry bridge（`session_tree.py`）

**设计目标**：`wait=false` 异步 spawn 后，子 Agent 可在 parent gateway stream 结束后继续运行；Server REST/SSE 与 cancel 必须在无 active gateway 或每消息新 agent 实例时仍能观测和控制这些任务。

**核心机制**（Harness `session_tree.py`，Server 薄封装于 `subagents.py` 与 `harness_bridge.py`）：
1. spawn 写入 `ACTIVE_SUBAGENTS` + `ACTIVE_SUBAGENT_SESSIONS`（`_manager_spawn.py`）
2. **list / SSE**：`merge_active_subagent_children(session_id, gateway_children)` 合并 gateway `list_children` 与 registry 行
3. **cancel-all**：当前 gateway agent 的 `cancel_all_children()` **加上** `cancel_active_children_for_session(session_id)`（每消息新建 agent 时 orphan manager 仍可达）
4. **cancel / steer 单任务**：直接查 `ACTIVE_SUBAGENTS[task_id]`（无需 gateway）
5. **resume**：仍需 active gateway parent agent（需 `subagent_manager.resume_from_checkpoint`）

**与 OpenClaw 对齐点**：类似 `subagent-registry` + `killSubagentRunAdmin`——registry 独立于 parent turn 生命周期。

**Prompt Cache**：纯 Server/Harness 控制面，零 LLM prompt 影响。

---

## 参考资料

- 模块索引：[_ARCH.md](_ARCH.md)（维护者 roadmap 仅在私有 vortexai `temp-docs/`，非本仓路径）

### DAG 并发执行与动态并发裂变 (Swarm Fission)
`orchestrator.py` 提供了 `execute_dag_plan`，支持基于有向无环图 (DAG) 的并发执行模式。
- 引入 `StateReducer` 解决 LLM 并发时的状态读写冲突 (Race Conditions)。
- 引入 `ConcurrencyLimiter` 控制并发上限。
- **声明式依赖过滤**：在注入 `dag_previous_results` 时，严格根据 `step.dependencies` 过滤，仅将直接父节点的结果注入上下文，实现 **Zero-Cognitive-Load** 的上下文精准隔离，彻底解决 Token 爆炸和幻觉问题。
- **运行时动态并发裂变 (Swarm Fission)**：通过 `delegate_task_tool(mode=parallel)`，Agent 可以在运行时触发并行 Map-Reduce。工具通过 `langgraph.types.interrupt` 挂起当前 Agent（`SubAgentStatus.YIELDED`），Server 侧 `stream_with_swarm_fission_resume` 调用 Harness `execute_swarm_fission`（与 batch 同源 spawn）执行 `TaskRequest[]`，完成后以 `Command(resume=ParallelTaskResults)` 恢复父 Agent 汇总结果。

- **Auto-Vaulting (自动落盘)**：当子 Agent 最终结果超过 `SubagentConfig.auto_vault_threshold`（默认 8000 字符，YAML 可配）时，`_auto_vault_or_truncate` 将其写入 `ArtifactVault`（`ISOLATED_COPY` 时写入 `_isolated_parent_workspace` 以便父 Agent/GUI 可读）并替换为摘要 + `vault://` 指针及 `file_read_tool(paths=["vault://…"])` 恢复提示；若当前 `ArtifactContext` 活跃，同时 `push_inline_artifact` 推送前端 SSE 卡片。父 Agent 用 `file_read_tool` 读 `vault://` URI 恢复全文，**不提供** LLM 侧 vault_put/get/extract 元工具（与 Hermes/deer-flow 行业做法一致）。
