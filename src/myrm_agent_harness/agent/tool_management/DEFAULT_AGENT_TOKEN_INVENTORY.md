# 默认 Agent 初始 Token 逐项清单

> 测量方法：`tiktoken cl100k_base` 编码器（OpenAI 标准）
> 测量时间：2026-05-02
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

## 二、CORE 工具层（~255 tokens，始终加载，排最前面 → 永远被缓存）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 4 | web_fetch_tool | 255 | `harness/toolkits/web_fetch/web_fetch_agent_tools.py` | HTTP 请求/网页抓取（含 fetch_and_extract + fetch_full_content 两种操作说明） | 始终 |

**注意**：`web_fetch_tool` 的 token 取决于是否启用 advanced_retrieval：启用时 255 tokens（含 extract），未启用时 ~51 tokens。

---

## 三、COMMON 工具层（~4,457 tokens，默认开启可关）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 5 | **request_answer_user_tool** | **1,024** | `harness/agent/meta_tools/answer_user_tool.py` | 回复自审工具，包含完整的自审流程和回复质量检查逻辑 | 默认开启（`enable_answer_tool=True`） |
| 6 | **bash_code_execute_tool** | **1,207** | `harness/agent/meta_tools/bash/bash_tool.py` | Shell/Python 代码执行，包含执行规则、依赖分析、优化策略、严格禁止项。另有 OS_HINT (~50 tokens) 动态追加 | 默认开启 |
| 7 | file_edit_tool | 155 | `harness/agent/meta_tools/file_ops/file_edit_tool.py` | 精确编辑 (str_replace) | 默认开启 |
| 8 | file_read_tool | 390 | `harness/agent/meta_tools/file_ops/file_read_tool.py` | 读取文件内容 | 默认开启 |
| 9 | file_write_tool | 131 | `harness/agent/meta_tools/file_ops/file_write_tool.py` | 创建/覆盖写入文件 | 默认开启 |
| 10 | planner_tool | 373 | `harness/toolkits/tasks/planner_agent_tools.py` | 复杂任务规划/分解 | 默认开启 |
| 11 | **web_search_tool** | **1,177** | `harness/toolkits/web_search/web_search_agent_tools.py` | 网络搜索，含搜索引擎选择逻辑、查询重写规则、多引擎支持说明 | 默认开启，前端可关闭 |

**注意**：
- `bash_code_execute_tool` 的实际 token 包含 `TOOL_DESCRIPTION`(1,207) + `_get_os_hint()`(~50) + `ptc_desc`(~80, PTC 内置工具描述) = ~1,337 tokens

---

## 四、EXTENDED 工具层（按需加载，放最后 → 变化不影响前面的缓存）

### 4.1 默认加载的 EXTENDED 辅助工具（enable_file_tools 时）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 12 | glob_tool | 234 | `harness/agent/meta_tools/file_search/glob_tool.py` | 通配符文件搜索 |
| 13 | grep_tool | 349 | `harness/agent/meta_tools/file_search/grep_tool.py` | 正则内容搜索 |

### 4.2 记忆工具（启用记忆系统时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 17 | memory_recall_tool | 378 | `harness/toolkits/memory/memory_agent_tools.py` | 检索相关记忆 |
| 18 | memory_save_tool | 111 | `harness/toolkits/memory/memory_agent_tools.py` | 保存信息到长期记忆 |
| 19 | memory_manage_tool | 181 | `harness/toolkits/memory/memory_agent_tools.py` | 管理/删除记忆条目 |

### 4.3 技能工具（有技能后端时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 20 | skill_select_tool | 125 | `harness/agent/meta_tools/skills/select/skill_select_tool.py` | 加载技能 SOP 文档 |
| 21 | skill_manage_tool | 251 | `harness/agent/meta_tools/skills/manage/skill_manage_tool.py` | 创建/修改/删除技能 |
| 22 | discover_capability_tool | 236~299 | `harness/agent/meta_tools/discover_capability/discover_capability_tool.py` | 统一能力发现（BM25+Embedding 语义搜索） |
| 23 | skill_discovery_tool | 192 | `harness/agent/meta_tools/skills/discovery/skill_discovery_tool.py` | 从外部源安装/卸载技能 |
| 24 | skill_analyze_tool | 77 | `harness/agent/meta_tools/skills/analyze/skill_analyze_tool.py` | 技能质量分析和遗忘建议 |

### 4.4 历史会话搜索工具

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 25 | conversation_search_tool | 237 | `harness/toolkits/memory/conversation_search/tool.py` | 搜索历史会话证据片段与预计算摘要 |

### 4.5 交互工具（harness 提供，按配置加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 26 | ask_question_tool | 98 | `harness/agent/meta_tools/clarification/clarification_agent_tools.py` | 向用户提出结构化澄清问题，单轮仅可调用一次 | enable_ask_question=True |
| 27 | render_ui_tool | 1,254 | `harness/agent/meta_tools/interaction/render_ui_tool.py` | 交互式 UI 渲染（表单/卡片/表格） | enable_render_ui=True |

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
| 43 | browser_local_search_tool | 113 | `myrm-agent-server/app/services/local_browser/local_browser_data_agent_tools.py` | 本地浏览器书签/历史搜索（server 层，local mode） |

### 4.8 Bash 后台进程工具（enable_bash 时 deferred 注册，discover_capability 按需挂载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 44 | bash_process_list_tool | 76 | `harness/agent/meta_tools/bash/bash_process_tools.py` | 列出当前会话的后台进程（deferred） |
| 45 | bash_process_output_tool | 55 | `harness/agent/meta_tools/bash/bash_process_tools.py` | 读取后台进程输出尾部（deferred） |
| 46 | bash_process_kill_tool | 38 | `harness/agent/meta_tools/bash/bash_process_tools.py` | 终止后台进程（deferred） |

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

### 4.18 内部 / 伪工具（默认通用 Agent Turn 1 = **0 token**）

以下 5 个名字登记在 `tool_layers.py`（供 registry 校验与 token 统计），**不会**进入默认通用 Agent 的 `registry.resolve()` / `bind_tools`：

| 工具组 | 默认通用 Agent | 实际占 token 的场景 |
|--------|:--------------:|---------------------|
| `dispatch_research` / `think` / `finalize_report` | 0 | 仅 Deep Research 编排器 LLM（`build_orchestrator_tools()`） |
| `submit_verdict` | 0 | 仅 Verification 子 Agent（`_orchestrator_verification.py` 动态注入） |
| `_completion_check` | 0 | deferred 注册；CompletionGuard 在 `aafter_model` 强制注入 tool_call，不占 Turn 1 schema |

表中 Token 列表示**若注入该 LLM 上下文时**的 schema 成本，非默认 Agent 固定开销。

### 4.20 Deep Research 编排器伪工具（仅深度搜索模式，JSON Schema 注入 LLM）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 83 | dispatch_research | 37 | `harness/agent/deep_research/tools.py` | 派遣研究子 Agent 调查特定主题（最多 3 个并行） | 深度搜索编排器内部；编排器截获 tool_call，无真实执行体 |
| 84 | think | 37 | `harness/agent/deep_research/tools.py` | 思维链推理暂存区（非推理模型适用） | 深度搜索编排器内部，reasoning model 时省略 |
| 85 | finalize_report | 26 | `harness/agent/deep_research/tools.py` | 通知编排器研究完成，进入报告生成阶段 | 深度搜索编排器内部 |

### 4.22 编排器验证子 Agent 内部工具

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 86 | submit_verdict | 26 | `harness/agent/sub_agents/_orchestrator_verification.py` | 提交验证裁决结果（passed/findings/confidence） | 验证子 Agent 内部注入；父编排器读取结构化 verdict |

### 4.23 框架内部工具（deferred，CompletionGuard 中间件注入）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 87 | _completion_check | 42 | `harness/agent/middlewares/completion_guard.py` | CompletionGuard 注入的完成验证检查点 | `deferred=True`（`_` 前缀）；guard 改写 tool_calls，不进默认 bind_tools |

### 4.24 Server 层业务工具（server 启动时动态注册，依赖第三方 SDK）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 88 | x_search_tool | 77 | `server/integrations/tools/x_live_search.py` | X/Twitter 实时搜索（xAI Live Search API） | Agent 启用 `x-live-search` prebuilt skill 时 [Deferred] |

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

## 七、用户消息

| 组件 | Token | 说明 |
|------|------:|------|
| 用户第一条消息 | ~20 | 典型短消息如 "用Python写一个快速排序函数" |
| `<current_datetime>` 标签 | ~12 | 注入到最后一条 HumanMessage 中的当前时间戳 |

---

## 总计估算

### 典型 Turn 1 场景（默认智能体，启用记忆+搜索+技能+高级检索）

| 分类 | Token (tiktoken) | 明细 |
|------|------------------:|------|
| System Prompt 层 | ~2,607 | 固定，跨用户缓存 |
| CORE 工具层 | ~255 | 1 工具，固定，始终缓存 |
| COMMON 工具层 | ~4,457 | 7 工具，默认存在 |
| EXTENDED 工具层 | ~2,096 | glob(234) + grep(349) + memory×3(670) + skill_select(125) + skill_manage(251) + discover_capability_tool(236) + conversation_search_tool(237) + …（deferred: bash_process×3 不占默认 prompt） |
| 工具 JSON schema | ~1,105 | ~17 工具 × ~65 tokens |
| 动态注入 | ~1,200 | user_instructions + memory_context + inline_skills |
| 消息格式 | ~500 | role tags, boundaries 等 |
| 用户消息 | ~32 | 短消息 + datetime 标签 |
| **tiktoken 小计** | **~12,261** | |
| Qwen tokenizer 差异 | +~200~900 | 取决于中文内容比例 |
| **Qwen 实测估计** | **~12,900~13,600** | |

### 最小 Turn 1 场景（仅 CORE 工具，无 COMMON/EXTENDED）

| 分类 | Token (tiktoken) |
|------|------------------:|
| System Prompt 层 | ~2,607 |
| CORE 工具层 | ~255 |
| 工具 JSON schema | ~65 (~1 工具) |
| 用户消息 | ~32 |
| 消息格式 | ~300 |
| **tiktoken 小计** | **~3,259** |

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
[CORE: web_fetch(255)]
  ↑ 始终缓存命中（~255 tokens）

[COMMON: request_answer_user(1024) bash(1207) file_edit(155) file_read(390) file_write(131) planner(373) web_search(1177)]
  ↑ 默认缓存命中，用户可通过前端开关控制（~4,457 tokens）

[EXTENDED: glob(234) grep(349) memory_*(670) skill_*(~600) ...]
  ↑ 按需变化，不影响 CORE/COMMON 缓存

[System Prompt: core(2188) + datetime_rules(91) + security_boundary(328)]
  ↑ 冻结，跨用户共享缓存

[Dynamic: user_instructions(~200) + memory_context(~500) + skills(~500)]
  ↑ 同用户会话内稳定
```

**实际缓存效果**：固定部分 ~7,300+ tokens 全部被缓存（仅收 5-10% 费用）→ 首轮后续调用大幅节省成本。

---

## 工具层级注册表 (tool_layers.py)

<!-- TOOL_COUNT_BEGIN -->
Tools registered: **90** (CORE 1 + COMMON 7 + EXTENDED 82). Source of truth: `tool_layers.py` (harness) + `_tool_layer_bootstrap.py` (server). Auto-generated by `scripts/validate_tool_registry.py --generate-docs`.
<!-- TOOL_COUNT_END -->
未注册的工具（如 MCP 动态工具）自动归入 EXTENDED，并在运行时打印 WARNING 日志。
完整列表请直接查看 `tool_layers.py`。
