# Meta-Tools System Design

> Agent 绑定元工具层。提供依赖 Agent 运行时基础设施（会话、Planner、HITL、子 Agent、Artifact 上下文）的 LangChain 工具，与 `toolkits/` 通用工具严格分离。

---

## 设计目标

1. **框架绑定 vs 通用工具分离**：`toolkits/` 可独立 import；`meta_tools/` 必须绑定 Agent 会话/运行时
2. **Claude Code 兼容**：bash、file_ops、file_search 等工具接口与 Claude Code 对齐，降低迁移成本
3. **条件加载**：通过 `tool_management/tool_layers.py` 三层（CORE/COMMON/EXTENDED）控制 token 开销
4. **单一委派入口**：子 Agent 创建统一走 `spawn_subagent/`，并行路径复用 `parallel/`

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│ SkillAgent / BaseAgent (_skill_agent_tools.py 装配)              │
│  tool_management/registry.py — 去重、排序、生命周期                 │
└────────────────────────────┬────────────────────────────────────┘
                             │ create_*_tools()
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ 执行面           │ │ 发现/交互面      │ │ 编排面           │
│ bash/           │ │ discover_       │ │ spawn_subagent/ │
│ file_ops/       │ │  capability/    │ │ skills/         │
│ file_search/    │ │ interaction/    │ │ goals/          │
│                 │ │ clarification/  │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                   │                   │
         └───────────────────┴───────────────────┘
                             ▼
              agent/artifacts · sub_agents · middlewares
              (ArtifactContext, delegate, completion_guard)
```

### 与 toolkits 边界

| 层级 | 路径 | 放什么 | 禁止 |
|------|------|--------|------|
| 通用原语 | `toolkits/` | 沙箱、检索、MCP 适配、Kanban 引擎 | import `agent/` |
| 框架元工具 | `agent/meta_tools/` | 需要会话/Planner/HITL 的工具包装 | 单一 SaaS 硬编码 |
| 业务 | `server/` + skills | OAuth、REST、prebuilt skills | 新 harness `@tool` |

详见 [tool_management/TOOL_DESIGN_STRATEGY.md](../tool_management/TOOL_DESIGN_STRATEGY.md) §1.2。

---

## 子模块职责

| 子模块 | 职责 | 关键出口 |
|--------|------|----------|
| `bash/` | PTY/bash 执行、输出压缩与 eviction | `bash_tool`, `bash_executor` |
| `file_ops/` | 读写编辑、validators、observers、vault 工具 | `file_read_tool`, `file_write_tool`, `file_edit_tool` |
| `file_search/` | glob/grep（Claude Code 兼容） | `glob_tool`, `grep_tool` |
| `spawn_subagent/` | delegate/batch/steer/cancel/teammate | `delegate_task_tool`, `batch_delegate_tasks_tool` |
| `skills/` | analyze/select/search/manage/discovery 技能工具 | `create_skill_*_tool` 系列（见各子目录） |
| `goals/` | Goal 引擎 LLM 工具面（域逻辑在 `agent/goals/`） | `create_goal_tools` |
| `clarification/` | 结构化 HITL 澄清 | `ask_question_tool` |
| `interaction/` | UI artifact 渲染 | `render_ui_tool` |
| `discover_capability/` | 统一能力发现网关 | `discover_capability_tool` |

根目录独立工具：

| 文件 | 职责 |
|------|------|
| `answer_user_tool.py` | 完成阶段门控信号（配合 `completion_guard`） |

> 运行时诊断由业务层 Settings Doctor UI + `/health/doctor` API 提供（`observability/diagnostics/probes.py`），不作为 Agent meta_tool。

---

## 装配与加载

1. **`_skill_agent_tools.py`** — SkillAgent mixin，按 profile/skill 条件组装 meta_tools + toolkits 工具
2. **`tool_management/tool_layers.py`** — CORE/COMMON/EXTENDED 分层 SSOT
3. **`DEFAULT_AGENT_TOKEN_INVENTORY.md`** — tiktoken 计量参考

Server 层通过 `factory.py` 的 `_setup_*_tools()` 注入 store/dispatcher 等运行时依赖；meta_tools 本身不 import server。

---

## 关键依赖

- `agent/sub_agents/` — 委派执行
- `agent/parallel/` — batch/swarm 并行 spawn
- `agent/artifacts/` — `@file_*` 短 ID、vault、UI registry
- `agent/middlewares/` — completion_guard、tool_interceptor、deferred_tool
- `toolkits/` — 底层执行（browser、code_execution、kanban 等）

---

## 扩展指南

新增 meta_tool 前自检：

1. 是否**必须**绑定 Agent 会话/运行时？否 → 放 `toolkits/`
2. 是否单一厂商 SaaS？是 → skill 或 MCP
3. 是否在 `tool_layers.py` 注册层级？
4. 更新 `_ARCH.md` + token inventory

---

## 参考资料

- [meta_tools/_ARCH.md](_ARCH.md) — 文件清单
- [tool_management/TOOL_DESIGN_STRATEGY.md](../tool_management/TOOL_DESIGN_STRATEGY.md)
- [sub_agents/SUB_AGENT_SYSTEM.md](../sub_agents/SUB_AGENT_SYSTEM.md)
