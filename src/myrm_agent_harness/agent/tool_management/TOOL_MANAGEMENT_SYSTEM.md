# Tool Management System Design

> LLM 工具（Action Tool）注册、分层、去重、排序与生命周期管理 SSOT。控制 LLM 动作空间复杂度（ASCS）与 token 预算。

---

## 术语（对外沟通）

| 对外说法 | 含义 | 当前规模 |
|----------|------|----------|
| **LLM 工具** / **工具** | `BaseTool` 注册进 `ToolRegistry` 与 `_TOOL_LAYERS`，LLM 通过 tool_call 执行 | **67**（CORE 7 + COMMON 5 + EXTENDED 55） |

对外文档与沟通中，**「工具」仅指 LLM 工具**。编排信号、runtime hook、toolkits 引擎、Skill 文档、PTC 等实现细节属于代码层，**不称为工具**。

下文 **Action Tool** 与 **LLM 工具** 同义（代码与 `validate_tool_registry.py` 沿用 Action Tool 命名）。

---

## 设计目标

1. **减少动作空间**：工具越少 → 决策越准（见 ASCS 指标）
2. **三层分级**：CORE / COMMON / EXTENDED — profile 可开关 COMMON/EXTENDED
3. **统一注册**：替代 BaseAgent 内 scattered dedup/sort
4. **框架 vs 业务边界**：harness 只放通用原语；SaaS 集成走 skill/MCP/server

---

## 系统架构

```
SkillAgent / Server factory
        ↓
tool_layers.py — CORE/COMMON/EXTENDED SSOT
        ↓
registry.py — dedup + sort + ToolBindMode (TURN1 LLM tools; RUNTIME_ONLY internal hooks)
        ↓
lifecycle_manager.py — init_tools / cleanup_tools
        ↓
action_space.py — ASCS _profiler
```

---

## 核心文件

| 文件 | 职责 |
|------|------|
| `tool_layers.py` | 三层优先级注册表；未注册工具 WARNING |
| `tool_catalog.py` | LLM Tool 角色/加载条件；Product ID 由 `TOOL_TO_GROUP` + `BUILTIN_TOOL_ID_TO_GROUP` 派生 |
| `registry.py` | 去重、排序、`ToolBindMode` 三分绑定 |
| `lifecycle_manager.py` | 工具 init/cleanup 编排 |
| `lifecycle_protocol.py` | `LifecycleAwareTool` Protocol |
| `action_space.py` | ActionSpaceProfiler / ASCS |
| `types.py` | `ToolBindMode` + 子系统类型 |
| `TOOL_DESIGN_STRATEGY.md` | 设计策略与竞品对比 |
| `DEFAULT_AGENT_TOKEN_INVENTORY.md` | tiktoken 逐项计量 |

---

## 与 meta_tools / toolkits 边界

| 层 | 路径 | 职责 |
|----|------|------|
| 注册 SSOT | `tool_management/` | 谁在哪个 layer、token 计量 |
| 框架元工具 | `meta_tools/` | Agent 绑定工具实现 |
| 通用工具 | `toolkits/` | 可独立 import 的原语 |

Server `_tool_layer_bootstrap.py` 扩展 EXTENDED 层业务工具。

---

## 内部分类（实现 / token 会计，非产品术语）

以下四类**不计入 LLM 工具 67 个**，仅用于实现与 Turn1 token 隔离：

| 内部术语 | 含义 | SSOT |
|----------|------|------|
| **Orchestration Signal** | 专用 orchestrator 会话中的 JSON schema；Python 截获 tool_call | `agent/orchestration/signals/` |
| **Runtime Hook** | 中间件注入的 RUNTIME_ONLY 伪 tool_call | `agent/orchestration/hooks.py` |
| **PTC Runtime Tool** | Dynamic Workflow PTC 沙箱内 `myrm_tools.spawn_subagent` / `myrm_tools.notify`；零 Turn1 bind | `agent/dynamic_workflow/tools.py` · `scripts/tool_registry_config.py` `PTC_RUNTIME_TOOL_NAMES` |
| **非 LLM 实现** | 引擎、Skill 文档、REST 等普通代码 | `toolkits/`、`app/services/` 等 |

**只有 LLM 工具（Action Tool）使用 CORE / COMMON / EXTENDED 三层。**

PTC `spawn_subagent` 与 LLM `delegate_task_tool` 共用 `_spawn_child()` 下游，但调用者不同（Python 编排脚本 vs 主 Agent tool_call）。详见 [DYNAMIC_WORKFLOW_SYSTEM.md](../dynamic_workflow/DYNAMIC_WORKFLOW_SYSTEM.md)。

`tool_catalog.py` 仅服务 LLM 工具（`user_capability`）。**Product ID 列**由 `TOOL_TO_GROUP` + `BUILTIN_TOOL_ID_TO_GROUP` 派生。

<!-- TOOL_CATALOG_BEGIN -->
### LLM Tool Catalog (auto-generated)

Only **LLM tools** (`_TOOL_LAYERS` + ToolRegistry) appear here. Orchestration signals, runtime hooks, and PTC runtime tools (`spawn_subagent`, `notify`) are documented in §内部分类 above.

| Tool | Layer | Role | Product ID | Load condition |
|------|-------|------|------------|----------------|
| `bash_code_execute_tool` | CORE | user_capability | — | Agent baseline file_ops+code_execute; Turn1 |
| `file_edit_tool` | CORE | user_capability | — | Agent baseline file_ops; Turn1 |
| `file_read_tool` | CORE | user_capability | — | Agent baseline file_ops; Turn1 |
| `file_write_tool` | CORE | user_capability | — | Agent baseline file_ops; Turn1 |
| `glob_tool` | CORE | user_capability | — | Agent baseline file_ops; Turn1 |
| `grep_tool` | CORE | user_capability | — | Agent baseline file_ops; Turn1 |
| `web_fetch_tool` | CORE | user_capability | — | Agent baseline; Turn1 (Fast mode may omit file/bash only) |
| `memory_manage_tool` | COMMON | user_capability | memory | enable_memory + enabled_builtin_tools: memory |
| `memory_search_tool` | COMMON | user_capability | memory | enable_memory + enabled_builtin_tools: memory |
| `memory_save_tool` | COMMON | user_capability | memory | enable_memory + enabled_builtin_tools: memory |
| `todo_write` | COMMON | user_capability | planning | planning or existing workspace todos |
| `web_search_tool` | COMMON | user_capability | web_search | enabled_builtin_tools: web_search (default on) |
| `ask_question_tool` | EXTENDED | user_capability | structured_clarify | server mount policy (interactive web_chat); requires_confirmation WebUI emphasis; ClarificationGuardMiddleware one call/turn |
| `bash_process_tool` | EXTENDED | user_capability | — | Turn1 when bash enabled |
| `browser_ask_human_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_execute_script_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_extract_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_inspect_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_interact_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_manage_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_navigate_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_snapshot_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `channel_notify_tool` | EXTENDED | user_capability | — | Agent notify_targets configured |
| `complete_goal_tool` | EXTENDED | user_capability | — | active Goal on chat |
| `conversation_search_tool` | EXTENDED | user_capability | memory | Harness test/legacy factory only; product uses `memory_search_tool` sessions ACL |
| `cron_manage_tool` | EXTENDED | user_capability | cron | user cron capability wired |
| `delegate_task_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `delegate_to_agent_tool` | EXTENDED | user_capability | external_cli | external ACP agent configured |
| `desktop_interact_tool` | EXTENDED | user_capability | computer_use | enabled_builtin_tools: computer_use |
| `desktop_snapshot_tool` | EXTENDED | user_capability | computer_use | enabled_builtin_tools: computer_use |
| `desktop_vision_tool` | EXTENDED | user_capability | computer_use | enabled_builtin_tools: computer_use |
| `discover_capability_tool` | EXTENDED | user_capability | — | Turn1 when searchable skills exist |
| `image_tool` | EXTENDED | user_capability | image_generation | enabled_builtin_tools: image_generation |
| `kanban_add_task` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_attach` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban (worker) |
| `kanban_block` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_comment` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_complete` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_heartbeat` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_list_tasks` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_show` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_unblock` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `memory_search_tool` | EXTENDED | user_capability | — | enable_wiki + enable_memory (non-incognito) |
| `render_ui_tool` | EXTENDED | user_capability | render_ui | enabled_builtin_tools: render_ui |
| `request_answer_user_tool` | EXTENDED | user_capability | answer_tool | enabled_builtin_tools: answer_tool |
| `send_teammate_message_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `skill_discovery_tool` | EXTENDED | user_capability | — | Turn1 when discovery_backend present |
| `skill_manage_tool` | EXTENDED | user_capability | — | write_backend present |
| `skill_select_tool` | EXTENDED | user_capability | — | skill_backend present |
| `subagent_control_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `tts_generate` | EXTENDED | user_capability | tts | enabled_builtin_tools: tts |
| `update_ui_data_tool` | EXTENDED | user_capability | render_ui | enabled_builtin_tools: render_ui |
| `video_tool` | EXTENDED | user_capability | video_generation | enabled_builtin_tools: video_generation |
| `wiki_ingest_tool` | EXTENDED | user_capability | wiki | enabled_builtin_tools: wiki |
| `wiki_query_tool` | EXTENDED | user_capability | wiki | enabled_builtin_tools: wiki |
| `x_search_tool` | EXTENDED | user_capability | — | x-live-search prebuilt skill bound |
<!-- TOOL_CATALOG_END -->

---

## CI 集成

```bash
python scripts/validate_tool_registry.py          # 注册一致性
python scripts/validate_tool_registry.py --generate-docs  # 刷新 TOOL_COUNT + LLM Tool Catalog 块
```

---

## 扩展指南

1. 新 harness LLM Tool → `register_tool_layer()` + meta_tools 或 toolkits 实现 + `tool_catalog.py` load/role 条目；若属 togglable 能力族，同步 `TOOL_GROUP_MAP`（product ID 自动派生）
2. 更新 token inventory（`python scripts/measure_turn1_token_inventory.py` + 同步 `DEFAULT_AGENT_TOKEN_INVENTORY.md`）
3. 运行 `python scripts/validate_tool_registry.py --generate-docs`

编排信号与 runtime hook 见 `agent/orchestration/`（不在下方 LLM Tool Catalog 表内）。

## ToolBindMode 绑定契约

`ToolBindMode`（`types.py`）两分绑定语义如下：

| 模式 | Turn1 schema | 执行池（ToolNode / dynamic resolve） |
|------|--------------|--------------------------------------|
| `TURN1` | ✅ 绑定 | ❌（已在 Turn1） |
| `RUNTIME_ONLY` | ❌ | ✅（中间件注入，用户无感） |

**API 契约**（`registry.py`）：

- `resolve()` — 仅返回 `TURN1` 工具（LLM 首回合可见 schema）
- `get_runtime_tools()` — 仅 `RUNTIME_ONLY`（中间件注入的延迟执行钩子）

**典型映射**：

- 所有 LLM Action Tool → `TURN1`（按 profile 条件装配；MCP 超标整服降级 PTC Skill）
- `_completion_check`（CompletionGuard）→ `RUNTIME_ONLY`（名称 `_` 前缀自动推断）

**已删除**：`ToolBindMode.DISCOVERABLE`、`get_discoverable_tools()`、`discoverable_tools` 构造参数。低频能力改由 profile 开关 + MCP PTC 路由 + `discover_capability_tool`（搜索已绑定 Agent 的技能库）承担。

**禁止**：`get_deferred_tools()` 已删除；新代码不得混用 `deferred_tools` / `discoverable_tools` 变量名。

**GUI 暴露**（`emit_tools_snapshot`）：仅序列化 `TURN1` 工具，与 `resolve()` 一致；`RUNTIME_ONLY` 不进 `tools_snapshot` SSE。每条 snapshot 含可选 `builtin_tool_id`（Harness 内由 `get_tool_product_id()` 派生，无 i18n）；WebUI wrench 与 gap toast 共用 `builtinTools.ts` 中的本地化 capability 标签。

---

## 参考资料

- [tool_management/_ARCH.md](_ARCH.md)
- [TOOL_DESIGN_STRATEGY.md](TOOL_DESIGN_STRATEGY.md)
- [meta_tools/META_TOOLS_SYSTEM.md](../meta_tools/META_TOOLS_SYSTEM.md)
