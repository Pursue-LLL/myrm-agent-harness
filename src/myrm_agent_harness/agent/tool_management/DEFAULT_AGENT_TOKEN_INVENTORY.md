# 默认 Agent 初始 Token 逐项清单

> 测量方法：`tiktoken cl100k_base` 编码器（OpenAI 标准）
> 测量时间：2026-07-03（P3 重测，`scripts/measure_turn1_token_inventory.py`）
> 测量对象：默认通用智能体，Turn 1 初始化时的完整 prompt 结构

---

## 一、System Prompt 层（~2,607 tokens）

| # | 组件 | Token (tiktoken) | 来源文件 | 说明 |
|---|------|------------------:|----------|------|
| 1 | CORE_SYSTEM_PROMPT | ~1,700 | `server/prompts/general_agent_prompt.py` | 身份(_IDENTITY_CORE) + 精简 RULESET + RESPONSE_RULES + SECURITY_RULES。通用防御规则（XML 防御、上下文优先）已下沉至框架层 AGENT_CORE_RULES |
| 2 | DATETIME_SYSTEM_RULES | 91 | `harness/agent/streaming/utils.py` | 时间感知规则常量（`<datetime_rules>` 标签），冻结在 system prompt 中 |
| 3 | SecurityBoundary 数据边界规则 | 328 | `harness/agent/security/detection/content_boundary.py` | 由 SecurityBoundaryMiddleware 注入的 `<data_boundary_rules>` |

**缓存特性**：System Prompt 完全冻结（无动态内容），跨用户共享缓存。

---

## 二、CORE 工具层（7 个；通用 Agent Turn1 bind 7 个，2026-07-03 实测）

> 通用 Agent 基线：`web_fetch` + file×3 + bash + glob/grep（`tool_layers.py:57-63`）。Fast 模式由 converter 关闭 file/bash。

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 4a | web_fetch_tool | 280 | `harness/toolkits/web_fetch/web_fetch_agent_tools.py` | HTTP 抓取/深读 | Turn1 基线 |
| 6 | **bash_code_execute_tool** | **2,356** | `harness/agent/meta_tools/bash/bash_code_execute_tool.py` | Shell/Python；resolve 后含 PTC 动态工具描述 | 通用 Agent 基线 |
| 7 | file_edit_tool | 175 | `harness/agent/meta_tools/file_ops/file_edit_tool.py` | 精确编辑 | 通用 Agent 基线 |
| 8 | file_read_tool | 489 | `harness/agent/meta_tools/file_ops/file_read_tool.py` | 读取文件 | 通用 Agent 基线 |
| 9 | file_write_tool | 153 | `harness/agent/meta_tools/file_ops/file_write_tool.py` | 创建/覆盖写入 | 通用 Agent 基线 |
| 10 | glob_tool | 263 | `harness/agent/meta_tools/file_search/glob_tool.py` | 通配符搜索 | 通用 Agent 基线 |
| 11 | grep_tool | 344 | `harness/agent/meta_tools/file_search/grep_tool.py` | 正则搜索 | 通用 Agent 基线 |

**CORE 描述小计（Turn1 实测）**：**~4,060 tokens**（7 工具）

---

## 三、COMMON 工具层（注册 6 个；memory 三件套 + GUI 可开关单工具）

默认 Turn1 bind：**memory×3 + web_search**（`DEFAULT_ENABLED_BUILTIN_TOOLS` 含 memory；conversation_search **默认不 bind**，见用户设置 `memoryEnableConversationSearch`）。

组内排序（`get_tool_registry_sort_key`）：**memory 块 → web_search → answer → todo**。

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 12 | **memory_recall_tool** | **362** | `harness/toolkits/memory/memory_agent_tools.py` | 检索长期记忆 | enable_memory |
| 13 | **memory_save_tool** | **684** | 同上 | 写入长期记忆 | enable_memory |
| 14 | **memory_manage_tool** | **247** | 同上 | 更新/删除/纠正记忆 | enable_memory |
| 15 | **web_search_tool** | **1,175** | `harness/toolkits/web_search/web_search_agent_tools.py` | 网络搜索 | GUI 可关 |
| 16 | **request_answer_user_tool** | **1,024** | `harness/agent/meta_tools/answer_user_tool.py` | 回复自审 | 默认关闭（`answer_tool` opt-in） |
| 17 | todo_write | ~150 | `harness/agent/meta_tools/progress/todo_write_tool.py` | 主 Agent 多步进度 | 默认关闭（`planning` / Goal） |

**COMMON Turn1 实测（默认 profile）**：**~2,468 tokens**（4 工具；memory×3 + web_search）

---

## 四、EXTENDED 工具层（按需加载，放最后 → 变化不影响前面的缓存）

### 4.1 glob/grep（已迁至 §二 CORE）

glob_tool / grep_tool 登记在 CORE 层，Turn1 与 file 工具一并 bind。见 §二。

### 4.2 历史会话搜索（opt-in，Server 装配）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 18 | conversation_search_tool | 67 | `harness/toolkits/memory/conversation_search/tool.py` | 历史会话证据检索 | **默认关闭**；`memoryEnableConversationSearch=true` 且非无痕 |

### 4.3 技能工具（有技能后端时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 20 | skill_select_tool | 295 | `harness/agent/meta_tools/skills/select/skill_select_tool.py` | 加载技能 SOP 文档 |
| 21 | skill_manage_tool | 251 | `harness/agent/meta_tools/skills/manage/skill_manage_tool.py` | 创建/修改/删除技能 |
| 22 | discover_capability_tool | 238 | `harness/agent/meta_tools/discover_capability/discover_capability_tool.py` | 统一能力发现 |
| 23 | skill_discovery_tool | 192 | `harness/agent/meta_tools/skills/discovery/skill_discovery_tool.py` | 从外部源安装/卸载技能 | **DISCOVERABLE**（discover 挂载；有 ToolRegistry 时） |

### 4.4 历史会话搜索工具

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 25 | conversation_search_tool | 67 | `harness/toolkits/memory/conversation_search/tool.py` | 历史会话证据检索 |

### 4.5 交互工具（harness 提供，按配置加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 26 | ask_question_tool | 98 | `harness/agent/meta_tools/clarification/clarification_agent_tools.py` | 向用户提出结构化澄清问题，单轮仅可调用一次 | enable_ask_question=True |
| 27 | render_ui_tool | 223 | `harness/agent/meta_tools/interaction/render_ui_tool.py` | 交互式 UI 渲染（表单/卡片/表格）；spec 见 `.agent/docs/A2UI_REFERENCE.md` | enable_render_ui=True |

### 4.6 子 Agent 委托工具（有子 Agent 配置时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 28 | delegate_task_tool | 120 | `harness/agent/meta_tools/spawn_subagent/delegate_task_tool.py` | 委托任务给子 Agent |
| 29 | batch_delegate_tasks_tool | 52 | `harness/agent/meta_tools/spawn_subagent/delegate_task_tool.py` | 批量委托任务 |
| 30 | delegate_parallel_tasks_tool | 81 | `harness/agent/meta_tools/spawn_subagent/_delegate_batch.py` | Swarm Fission 并行委托（Yield-Resume 语义） |
| 31 | list_subagents_tool | 6 | `harness/agent/meta_tools/spawn_subagent/agent_manage_tool.py` | 列出子 Agent |
| 33 | cancel_subagent_tool | 6 | `harness/agent/meta_tools/spawn_subagent/agent_manage_tool.py` | 取消子 Agent |
| 34 | steer_subagent_tool | 11 | `harness/agent/meta_tools/spawn_subagent/agent_manage_tool.py` | 引导子 Agent |
| 35 | send_teammate_message_tool | 40 | `harness/agent/meta_tools/spawn_subagent/send_teammate_tool.py` | 子 Agent 间 P2P 直接通信（队友邮箱） |
| 36 | delegate_to_agent_tool | 216 | `harness/toolkits/acp/acp_agent_tools.py` | ACP 协议 Agent 委托（有 ACP 配置时） |

### 4.7 浏览器工具（启用浏览器时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 37 | browser_navigate_tool | 18 | `harness/toolkits/browser/tools/navigate.py` | 浏览器导航 |
| 38 | browser_snapshot_tool | 115 | `harness/toolkits/browser/tools/snapshot.py` | 页面快照 |
| 39 | browser_interact_tool | 66 | `harness/toolkits/browser/tools/interact.py` | 页面交互 |
| 40 | browser_extract_tool | 95 | `harness/toolkits/browser/tools/extract.py` | 内容提取 |
| 41 | browser_inspect_tool | 82 | `harness/toolkits/browser/tools/inspect.py` | 元素检查 |
| 42 | browser_manage_tool | 159 | `harness/toolkits/browser/tools/manage.py` | 浏览器管理 |

### 4.8 Bash 后台进程工具（enable_bash 时 DISCOVERABLE 注册，discover_capability 按需挂载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 44 | bash_process_tool | ~120 | `harness/agent/meta_tools/bash/bash_process_tools.py` | 后台进程 list/output/kill（DISCOVERABLE，spawn AutoMount） |

### 4.9 定时任务工具（启用 Cron 时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 47 | cron_manage_tool | 827 | `harness/toolkits/cron/cron_agent_tools.py` | 定时任务管理（创建/编辑/暂停/删除/列表） |

### 4.10 Wiki 知识库工具（有 Wiki 目录时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 48 | wiki_query_tool | 33 | `harness/toolkits/wiki/wiki_agent_tools.py` | 查询 Wiki 知识库 |
| 49 | wiki_ingest_tool | 62 | `harness/toolkits/wiki/wiki_agent_tools.py` | 导入内容到 Wiki |
| 50 | wiki_compile_tool | 71 | `harness/toolkits/wiki/wiki_agent_tools.py` | 编译 Wiki 文档 |
| 51 | wiki_maintain_tool | 84 | `harness/toolkits/wiki/wiki_agent_tools.py` | 维护 Wiki（清理/合并） |

### 4.11 Goal 目标工具

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 56 | get_goal_status_tool | 115 | `harness/agent/meta_tools/goals/goal_agent_tools.py` | 获取当前活跃目标状态 |
| 57 | update_goal_status_tool | 132 | `harness/agent/meta_tools/goals/goal_agent_tools.py` | 更新目标状态（仅允许 complete） |

### 4.13 看板工具（启用看板时加载，按角色分组）

**Server bind 策略**：Chat Agent + kanban → `orchestrator` 8 工具（~1,636 tok）；`KanbanTaskRunner` → `worker` 5 工具（~948 tok）；`full` 16 工具仅显式 `kanban_tool_mode=full`。解析：`myrm-agent-server/app/ai_agents/general_agent/kanban_tool_mode.py`。

#### Worker 工具（5 个）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 58 | kanban_show | 75 | `harness/toolkits/kanban/kanban_agent_tools.py` | 查看当前任务详情（描述/依赖/历史） |
| 59 | kanban_complete | 248 | `harness/toolkits/kanban/kanban_agent_tools.py` | 标记任务完成并提交结构化交接 |
| 60 | kanban_block | 298 | `harness/toolkits/kanban/kanban_agent_tools.py` | 阻塞任务（支持定时自动解除） |
| 61 | kanban_heartbeat | 100 | `harness/toolkits/kanban/kanban_agent_tools.py` | 报告运行中任务的进度（防僵尸回收） |
| 62 | kanban_comment | 227 | `harness/toolkits/kanban/kanban_agent_tools.py` | 跨任务评论协调（不限所有权，Worker 可评论任意任务） |

#### Orchestrator 工具（8 个）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 63 | kanban_add_task | 616 | `harness/toolkits/kanban/kanban_agent_tools.py` | 添加新任务（支持依赖/优先级/技能/幂等） |
| 64 | kanban_list_tasks | 119 | `harness/toolkits/kanban/kanban_agent_tools.py` | 列出看板任务（按状态/Agent 过滤） |
| 65 | kanban_update_task | 453 | `harness/toolkits/kanban/kanban_agent_tools.py` | 更新任务属性（标题/描述/优先级/超时/技能） |
| 66 | kanban_move_task | 116 | `harness/toolkits/kanban/kanban_agent_tools.py` | 变更任务状态（backlog/ready/blocked/archived） |
| 67 | kanban_delete_task | 66 | `harness/toolkits/kanban/kanban_agent_tools.py` | 删除任务（自动级联处理子任务依赖） |
| 68 | kanban_board_summary | 67 | `harness/toolkits/kanban/kanban_agent_tools.py` | 获取看板统计（各状态任务计数） |
| 69 | kanban_add_dependency | 109 | `harness/toolkits/kanban/kanban_agent_tools.py` | 添加任务依赖关系 |
| 70 | kanban_remove_dependency | 90 | `harness/toolkits/kanban/kanban_agent_tools.py` | 移除任务依赖关系 |

#### Management 工具（3 个，仅 full 模式）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 71 | kanban_create_board | 87 | `harness/toolkits/kanban/kanban_agent_tools.py` | 创建新看板 |
| 72 | kanban_list_boards | 42 | `harness/toolkits/kanban/kanban_agent_tools.py` | 列出所有看板 |
| 73 | kanban_get_task | 70 | `harness/toolkits/kanban/kanban_agent_tools.py` | 按 ID 获取任意任务详情 |

### 4.17 桌面语义控制工具（启用 Computer Use 时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 77 | desktop_inspect_tool | ~45 | `harness/toolkits/computer_use/desktop_agent_tools.py` | 前台应用/窗口元数据与工作流提示 |
| 78 | desktop_snapshot_tool | ~55 | `harness/toolkits/computer_use/desktop_agent_tools.py` | AX 树 + @dref，可选截图 |
| 79 | desktop_interact_tool | ~50 | `harness/toolkits/computer_use/desktop_agent_tools.py` | @dref 语义交互 |
| 80 | desktop_vision_tool | ~60 | `harness/toolkits/computer_use/desktop_agent_tools.py` | 显式截图/坐标回退 |

### 4.18 控制面工具（Control-Plane Tools；默认 Turn 1 = **0 token**）

四类（不进 GeneralAgent 默认 `bind_tools`）：

| 类型 | 工具 | 执行方式 |
|------|------|----------|
| 编排信号 | `dispatch_research` / `think` / `finalize_report` | DR 编排器截获 tool_call |
| Guard 注入 | `_completion_check` | CompletionGuard `RUNTIME_ONLY` + 运行时注入 |
| 验证交接 | `submit_verdict` | Verifier 子 Agent 动态注入 |
| PTC 桥接 | `spawn_subagent` / `notify`（见 §4.25） | DW 脚本 `myrm_tools.*`，非 LLM schema |

登记在 `tool_layers.py` 供 registry 校验；**不会**进入默认 `registry.resolve()`（`test_internal_tools_not_default_loaded.py`）。

| 工具组 | 默认通用 Agent | 实际占 token 的场景 |
|--------|:--------------:|---------------------|
| DR 三件套 | 0 | Deep Research 编排器（产品 **UNDER_DEVELOPMENT** gate，代码保留） |
| `submit_verdict` | 0 | Verification 子 Agent |
| `_completion_check` | 0 | CompletionGuard 收尾轮（非 Turn1） |

### 4.20 Deep Research 编排器控制面工具（JSON Schema 注入 LLM）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 83 | dispatch_research | 37 | `harness/agent/deep_research/tools.py` | 派遣研究子 Agent 调查特定主题（最多 3 个并行） | 深度搜索编排器内部；编排器截获 tool_call，无真实执行体 |
| 84 | think | 37 | `harness/agent/deep_research/tools.py` | 思维链推理暂存区（非推理模型适用） | 深度搜索编排器内部，reasoning model 时省略 |
| 85 | finalize_report | 26 | `harness/agent/deep_research/tools.py` | 通知编排器研究完成，进入报告生成阶段 | 深度搜索编排器内部 |

### 4.22 编排器验证子 Agent 内部工具

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 86 | submit_verdict | 26 | `harness/agent/sub_agents/_orchestrator_verification.py` | 提交验证裁决结果（passed/findings/confidence） | 验证子 Agent 内部注入；父编排器读取结构化 verdict |

### 4.23 框架内部工具（runtime-only，CompletionGuard 中间件注入）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 87 | _completion_check | 42 | `harness/agent/middlewares/completion_guard.py` | CompletionGuard 注入的完成验证检查点 | `ToolBindMode.RUNTIME_ONLY`；不进 discover；guard 改写 tool_calls |

### 4.24 Server 层业务工具（server 启动时动态注册，依赖第三方 SDK）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 88 | x_search_tool | 77 | `server/integrations/tools/x_live_search.py` | X/Twitter 实时搜索（xAI Live Search API） | Agent 绑定 `x-live-search` prebuilt skill 时 [Turn1] |
| 89 | channel_notify_tool | 333 | `server/services/agent/outbound_notify/channel_notify_tool.py` | Agent 主动 IM 出站（白名单+频控+附件） | Agent 配置 `notify_targets` 时 [Turn1] |

### 4.25 Dynamic Workflow PTC 桥接（非 tool_layers 登记）

| 名称 | 暴露形式 | 说明 |
|------|----------|------|
| `spawn_subagent` | `myrm_tools.spawn_subagent()` | PTC 脚本内阻塞 spawn；≠ LLM `delegate_task_tool` |
| `notify` | `myrm_tools.notify()` | Workflow 阶段 SSE；0 Turn1 bind |

---

## 五、动态注入内容（~1,200 tokens，Turn 1 典型值）

| 组件 | Token (估算) | 来源 | 说明 |
|------|------------:|------|------|
| user_instructions | ~200 | `server/agent_middlewares/user_instructions_middleware.py` | 用户自定义指令（SystemMessage，注入在 system prompt 之后） |
| Memory context | ~500 | `harness/agent/middlewares/memory_context_middleware.py` | Stable：`<user_memory_context>` **SystemMessage**；Learned：`wrap_untrusted` → `<<<UNTRUSTED_DATA>>>` **HumanMessage**（与 SecurityBoundary 契约一致）；统一 char 预算拆分 |
| Inline skills 列表 | ~500 | 技能系统 | `<skills>` 块内联展示可用技能名+描述（取决于已安装技能数量） |

**缓存特性**：
- `user_instructions` 同用户同会话内稳定，不破坏缓存
- `Memory context` 同用户连续对话内稳定（learned 内容仅会话结束后更新）
- `Inline skills` 同用户同技能配置内稳定

---

## 六、格式开销（~2,900 tokens，模型/API 相关）

| 组件 | Token (估算) | 说明 |
|------|------------:|------|
| 工具 JSON schema wrappers | ~65/tool | 每个工具的 API 格式额外开销（function name, parameters schema 等） |
| Qwen tokenizer 差异 | ~20-30% | Qwen3 tokenizer 对中文分词效率低于 tiktoken，中文内容 token 数会更高 |
| 特殊 token/消息格式 | ~500 | role tags, tool_use markers, message boundaries 等 |

---

## 七、Fast 模式 Turn1（`action_mode='fast'`）

> SSOT：`myrm-agent-server/app/services/agent/params/converter.py` · `params/_ARCH.md`

| 子模式 | Turn1 eager 工具 | 说明 |
|--------|------------------|------|
| normal | web_search + web_fetch + request_answer_user + memory×4（可选） | max_tool_calls=8 |
| deep | 同上 + SufficiencyConfig 增强搜索 | prompt 追加 `<deep_search_mode>`（web_fetch 深读 + answer 自审）；max_tool_calls=20 |

**不含**：file/bash/glob/grep、browser（browser 仅 Agent profile `browser` 开关 opt-in）、kanban、wiki、planning、子 Agent 委托。

---

## 八、用户消息

| 组件 | Token | 说明 |
|------|------:|------|
| 用户第一条消息 | ~20 | 典型短消息如 "用Python写一个快速排序函数" |
| `<current_datetime>` 标签 | ~12 | 注入到最后一条 HumanMessage 中的当前时间戳 |

---

## 总计估算

### 典型 Turn 1 场景（默认智能体，记忆+搜索+技能；无 answer/todo）

| 分类 | Token (tiktoken) | 明细 |
|------|------------------:|------|
| System Prompt 层 | ~2,607 | 固定，跨用户缓存 |
| CORE 工具层 | **~4,097** | 7 工具（2026-07-03 实测） |
| COMMON 工具层 | **~2,468** | memory×3 + web_search |
| EXTENDED 工具层 | **~769** | skill×2 + discover（默认无 conversation_search） |
| 工具 JSON schema | **~910** | 14 工具 × ~65 |
| 动态注入 | ~1,200 | user_instructions + memory_context + inline_skills |
| 消息格式 | ~500 | role tags, boundaries 等 |
| 用户消息 | ~32 | 短消息 + datetime 标签 |
| **tiktoken 小计** | **~12,583** | |

> bash Turn1 描述 token **~2,356**（含 PTC 动态工具摘要，随 resolve 工具集变化）。

### 最小 Turn 1 场景（仅 CORE 7 工具，无 COMMON/EXTENDED）

| 分类 | Token (tiktoken) |
|------|------------------:|
| System Prompt 层 | ~2,607 |
| CORE 工具层 | ~4,060 |
| 工具 JSON schema | ~455 (~7 工具 × ~65) |
| 用户消息 | ~32 |
| 消息格式 | ~300 |
| **tiktoken 小计** | **~7,454** |

### 满载场景（所有可选功能全开：浏览器+Cron+Wiki+子Agent+渲染UI+看板+日历+计算机+IM）

| 分类 | Token (tiktoken) |
|------|------------------:|
| System Prompt 层 | ~2,607 |
| CORE 工具层 | ~255 |
| COMMON 工具层 | ~4,457 |
| EXTENDED 全部（82 工具，harness 80 + server 2） | ~7,411+ |
| 工具 JSON schema | ~5,720 (~88 工具 × ~65) |
| 动态注入 | ~1,200 |
| 消息格式 | ~500 |
| **tiktoken 小计** | **~22,411+** |

---

## 缓存分层效果

```
[CORE: web_fetch + bash + file_* + glob + grep (~4,060 tok, 7 tools)]
  ↑ 通用 Agent 基线前缀（agent 模式）

[COMMON: memory_* + web_search (~2,468 tok)]
  ↑ memory 组优先；web_search GUI 可关

[EXTENDED: skill_* + discover (~769 tok); + conversation_search when opt-in]
  ↑ 按需变化，不影响 CORE/COMMON 前缀

[System Prompt: ~2,607]
  ↑ 冻结，跨用户共享缓存

[Dynamic: user_instructions(~200) + memory_context(~500) + skills(~500)]
  ↑ 同用户会话内稳定
```

**实测 Turn1 工具层合计**：描述 **7,379** + schema **975** = **8,354 tokens**（15 工具，`measure_turn1_token_inventory.py`）。

---

## 工具层级注册表 (tool_layers.py)

<!-- TOOL_COUNT_BEGIN -->
Tools registered: **79** (CORE 7 + COMMON 6 + EXTENDED 66). Source of truth: `tool_layers.py` (harness) + `_tool_layer_bootstrap.py` (server). Auto-generated by `scripts/validate_tool_registry.py --generate-docs`.
<!-- TOOL_COUNT_END -->
未注册的工具（如 MCP 动态工具）自动归入 EXTENDED，并在运行时打印 WARNING 日志。
完整列表请直接查看 `tool_layers.py`。
