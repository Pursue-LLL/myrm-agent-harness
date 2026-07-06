# Tool Management System Design

> Agent 工具注册、分层、去重、排序与生命周期管理 SSOT。控制 LLM 动作空间复杂度（ASCS）与 token 预算。

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
registry.py — dedup + sort + ToolBindMode (TURN1 / DISCOVERABLE / RUNTIME_ONLY)
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
| `tool_catalog.py` | LLM Tool 角色/加载条件 SSOT（`ToolCatalogRole`） |
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

## LLM Tool vs Agent Runtime（术语 SSOT）

| 术语 | 含义 | 示例 |
|------|------|------|
| **LLM Tool** | `BaseTool` 注册进 `ToolRegistry`，占 action space / token | `web_search_tool`, `bash_code_execute_tool` |
| **Agent Runtime** | 普通 Python 代码：引擎、中间件、编排状态机、Skill 文档体 | `KanbanService`, `CompletionGuard`, `SKILL.md` |

**只有 LLM Tool 使用 CORE / COMMON / EXTENDED 三层。** Runtime 模块禁止称作「工具」。

`tool_catalog.py` 为每个 `_TOOL_LAYERS` 登记项标注 `ToolCatalogRole`：

| Role | 含义 |
|------|------|
| `user_capability` | 产品能力（默认 GeneralAgent 路径） |
| `orchestration_signal` | 专用编排会话 LLM 信号（DR / Verifier；常由 Python 截获） |
| `runtime_hook` | 中间件注入（如 `_completion_check`） |

PTC 桥接（`myrm_tools.spawn_subagent` / `notify`）不在 `_TOOL_LAYERS` — 属于 Runtime，零 Turn1 schema。

<!-- TOOL_CATALOG_BEGIN -->
### LLM Tool Catalog (auto-generated)

Only **ToolRegistry** entries appear here. Agent runtime engines, middleware, skill documents, and PTC bridges are ordinary code — not LLM tools.

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
| `memory_recall_tool` | COMMON | user_capability | memory | enable_memory + enabled_builtin_tools: memory |
| `memory_save_tool` | COMMON | user_capability | memory | enable_memory + enabled_builtin_tools: memory |
| `request_answer_user_tool` | COMMON | user_capability | answer_tool | enabled_builtin_tools: answer_tool |
| `todo_write` | COMMON | user_capability | planning | planning or existing workspace todos |
| `web_search_tool` | COMMON | user_capability | web_search | enabled_builtin_tools: web_search (default on) |
| `dispatch_research` | EXTENDED | orchestration_signal | — | Deep Research orchestrator session only; intercepted |
| `finalize_report` | EXTENDED | orchestration_signal | — | Deep Research orchestrator session only; intercepted |
| `submit_verdict` | EXTENDED | orchestration_signal | — | Verifier sub-agent session only |
| `think` | EXTENDED | orchestration_signal | — | Deep Research orchestrator session only; intercepted |
| `_completion_check` | EXTENDED | runtime_hook | — | CompletionGuard RUNTIME_ONLY inject |
| `ask_question_tool` | EXTENDED | user_capability | — | clarification wiring in factory |
| `bash_process_tool` | EXTENDED | user_capability | — | DISCOVERABLE; discover_capability AutoMount |
| `batch_delegate_tasks_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `browser_ask_human_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_execute_script_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_extract_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_inspect_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_interact_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_manage_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_navigate_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `browser_snapshot_tool` | EXTENDED | user_capability | browser | enabled_builtin_tools: browser |
| `cancel_subagent_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `canvas_batch_layout` | EXTENDED | user_capability | canvas | enabled_builtin_tools: canvas |
| `canvas_get_selection` | EXTENDED | user_capability | canvas | enabled_builtin_tools: canvas |
| `canvas_get_state` | EXTENDED | user_capability | canvas | enabled_builtin_tools: canvas |
| `canvas_insert_element` | EXTENDED | user_capability | canvas | enabled_builtin_tools: canvas |
| `channel_notify_tool` | EXTENDED | user_capability | — | Agent notify_targets configured |
| `conversation_search_tool` | EXTENDED | user_capability | memory | memoryEnableConversationSearch opt-in |
| `cron_manage_tool` | EXTENDED | user_capability | — | user cron capability wired |
| `delegate_parallel_tasks_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `delegate_task_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `delegate_to_agent_tool` | EXTENDED | user_capability | — | external ACP agent configured |
| `desktop_inspect_tool` | EXTENDED | user_capability | computer_use | enabled_builtin_tools: computer_use |
| `desktop_interact_tool` | EXTENDED | user_capability | computer_use | enabled_builtin_tools: computer_use |
| `desktop_snapshot_tool` | EXTENDED | user_capability | computer_use | enabled_builtin_tools: computer_use |
| `desktop_vision_tool` | EXTENDED | user_capability | computer_use | enabled_builtin_tools: computer_use |
| `discover_capability_tool` | EXTENDED | user_capability | — | Turn1 when discoverable pool non-empty |
| `get_goal_status_tool` | EXTENDED | user_capability | — | active Goal on chat |
| `image_tool` | EXTENDED | user_capability | image_generation | enabled_builtin_tools: image_generation |
| `kanban_add_dependency` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_add_task` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_block` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_board_summary` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_comment` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_complete` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_create_board` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_delete_task` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_get_task` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_heartbeat` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_list_boards` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_list_tasks` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_move_task` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_remove_dependency` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_show` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `kanban_update_task` | EXTENDED | user_capability | kanban | enabled_builtin_tools: kanban |
| `list_subagents_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `render_ui_tool` | EXTENDED | user_capability | render_ui | enabled_builtin_tools: render_ui |
| `send_teammate_message_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `skill_discovery_tool` | EXTENDED | user_capability | — | DISCOVERABLE; skill marketplace |
| `skill_manage_tool` | EXTENDED | user_capability | — | write_backend present |
| `skill_select_tool` | EXTENDED | user_capability | — | skill_backend present |
| `steer_subagent_tool` | EXTENDED | user_capability | — | SubagentManagementExtension + entitlements |
| `tts_generate` | EXTENDED | user_capability | tts | enabled_builtin_tools: tts |
| `update_goal_status_tool` | EXTENDED | user_capability | — | active Goal on chat |
| `video_tool` | EXTENDED | user_capability | video_generation | enabled_builtin_tools: video_generation |
| `wiki_compile_tool` | EXTENDED | user_capability | wiki | enabled_builtin_tools: wiki |
| `wiki_ingest_tool` | EXTENDED | user_capability | wiki | enabled_builtin_tools: wiki |
| `wiki_maintain_tool` | EXTENDED | user_capability | wiki | enabled_builtin_tools: wiki |
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

1. 新 harness LLM Tool → `register_tool_layer()` + meta_tools 或 toolkits 实现 + `tool_catalog.py` load/role 条目
2. 更新 token inventory（`python scripts/measure_turn1_token_inventory.py` + 同步 `DEFAULT_AGENT_TOKEN_INVENTORY.md`）
3. 运行 `python scripts/validate_tool_registry.py --generate-docs`

编排信号与 runtime hook 的 role 见 `tool_catalog.py` 与下方 **LLM Tool Catalog** 生成表。

## ToolBindMode 绑定契约

`ToolBindMode`（`types.py`）三分绑定语义如下：

| 模式 | Turn1 schema | discover_capability 索引 | 执行池（ToolNode / dynamic resolve） |
|------|--------------|--------------------------|--------------------------------------|
| `TURN1` | ✅ 绑定 | ❌ | ❌（已在 Turn1） |
| `DISCOVERABLE` | ❌ | ✅ | ✅（AutoMount 后） |
| `RUNTIME_ONLY` | ❌ | ❌ | ✅（中间件注入，用户无感） |

**API 契约**（`registry.py`）：

- `resolve()` — 仅返回 `TURN1` 工具（LLM 首回合可见 schema）
- `get_discoverable_tools()` — 仅 `DISCOVERABLE`（discover 搜索 + AutoMount 候选）
- `get_runtime_tools()` — `DISCOVERABLE` + `RUNTIME_ONLY`（延迟执行与中间件钩子）

**典型映射**：

- MCP aggregate overflow、bash 后台进程、skill_discovery、cron → `DISCOVERABLE`
- `_completion_check`（CompletionGuard）→ `RUNTIME_ONLY`（名称 `_` 前缀自动推断）

**禁止**：`get_deferred_tools()` 已删除；新代码不得混用 `deferred_tools` 变量名，统一使用 `discoverable_tools`（构造参数）与上述三个 registry 方法。

**GUI 暴露**（`emit_tools_snapshot`）：仅序列化 `TURN1` 工具，与 `resolve()` 一致；`DISCOVERABLE` / `RUNTIME_ONLY` 不进 `tools_snapshot` SSE。

---

## 参考资料

- [tool_management/_ARCH.md](_ARCH.md)
- [TOOL_DESIGN_STRATEGY.md](TOOL_DESIGN_STRATEGY.md)
- [meta_tools/META_TOOLS_SYSTEM.md](../meta_tools/META_TOOLS_SYSTEM.md)
