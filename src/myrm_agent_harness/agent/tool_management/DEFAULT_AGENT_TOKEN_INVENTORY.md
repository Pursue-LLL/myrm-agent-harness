# 默认 Agent 初始 Token 逐项清单

> **术语**：下文 **「工具」= LLM 工具**（Action Tool）。§4.18 所列编排信号 / runtime hook **不是** LLM 工具，不计入 LLM 工具总数（见文末 `TOOL_COUNT` 自动生成块）。

> 测量方法：`tiktoken o200k_base` 规划 SSOT（`utils/text_utils.PLANNING_ENCODING`；与 GPT-5 / GPT-4o 族一致）
> 测量时间：2026-09-16（`scripts/measure_turn1_token_inventory.py`）
> 测量宿主：macOS 25.5.0 / arm64 / bash（OS hint、env 行、toolchain 探测行随宿主变化，见 §一、§二 标注）
> 测量对象：默认通用智能体，Turn 1 初始化时的完整 prompt 结构；`prompt_mode=full`、`enable_answer_tool=False`（server 默认）、locale EN（工具描述为主，prompt 主体见 §一 双列）
> 漂移门禁：`tests/scripts/test_measure_turn1_token_inventory.py` 锁定 §二–§四 逐工具数值，`tests/architecture/test_prompt_token_budget_gate.py` 锁定预算上限
>
> **三 tier 计量**：① UI 上下文环 = 上一轮 API `prompt_tokens`；② compress / summarize / emergency prune 预算 = messages + bind-tools overhead（本表）+ 可选 max(API)；③ 非 OpenAI 模型 client 估算存在偏差，账单以 provider usage 为准。

---

## 一、System Prompt 层（`messages[0]` 拼装 + `messages[1]` 安全边界）

> **口径**：tiktoken `o200k_base` 实测（`utils/text_utils.PLANNING_ENCODING`），宿主 macOS。
> `messages[0]` 由框架层 `agent/base_agent.py:178-183` **一次拼装**完成——业务层 CORE prompt 只是其中一段，框架层在其后追加 6 段；安全边界是 `messages[1]` 的**独立 SystemMessage**，不计入 `messages[0]`。

| # | 组件 | Token (o200k_base) | 来源文件 | 说明 |
|---|------|-------------------:|----------|------|
| 1 | CORE_SYSTEM_PROMPT | **662** (EN) / **1,021** (ZH) | `server/ai_agents/prompts/general_agent_prompt.py` | `prompt_mode=full` + `enable_answer_tool=False`（server 默认，`server/ai_agents/agents.py:132`）。开启 answer_tool 时为 738 / 1,103。组成 = identity + ABSOLUTE_OBEDIENCE + RESPONSE + TASK_INTEGRITY（来自 `shared_rules.py`） |
| 2 | DATETIME_SYSTEM_RULES | 89 | `harness/agent/streaming/utils.py:61` | 时间感知规则常量（`<datetime_rules>` 标签），冻结在 system prompt 中 |
| 3 | AGENT_CORE_RULES + TOOL_ENFORCEMENT | **477**（303 + 174） | `harness/agent/streaming/model_discipline.py:51/82` | L1 核心规则**无条件注入**；L2 工具执行约束按 `_ENFORCEMENT_FAMILIES`（gpt/codex/gemini/gemma/grok/glm/qwen/deepseek/claude/anthropic）命中注入，未命中族减 174 |
| 4 | 模型族纪律（L3/L3.5） | **530** GPT/Codex/Grok · 119 Claude · **+178** Opus 补充 · 163 Gemini · 106 DeepSeek/Qwen/GLM | 同上 | 按 model name 命中，**互斥**（`_FAMILY_DISCIPLINE`），只有 Opus 额外叠加 178 |
| 5 | resolve_escalation_contract（L4） | 189（模板 184 + 模型名占位） | `model_discipline.py:280` | 仅当配置 escalation 模型且与主模型**不同名**时注入，否则 0（`resolve_escalation_contract` 早返） |
| 6 | channel output hint | 56（web_chat / slack）· 52（voice）· 25（wechat）· 17（webhook）· 0（无渠道） | `harness/agent/streaming/channel_output_hints.py:176` | 按渠道名解析；命中 `CHANNEL_OUTPUT_HINTS` 常量表 |
| 7 | environment 行 | 43 (macOS) · 29 (Linux) · 31 (Windows/powershell) | `harness/toolkits/code_execution/platform.py:149` | `<environment>` 标签；含 OS/shell/可选 python-toolchain 与 VNC 探测行（干净环境为 0） |
| 8 | canary 指令 | **50~57**（均值 ≈53） | `harness/agent/security/detection/canary_guard.py:51` | `SECURITY CANARY: CANARY-<12 位 hex>`；随机 hex 触发 BPE 分裂，实测 300 次采样分布 50~57，**非字节恒定**但差异可忽略 |
| 9 | SecurityBoundary 数据边界规则（`messages[1]`） | **299** | 定义于 `harness/core/security/detection/content_boundary.py:391`（`agent/security/detection/content_boundary.py` 为 re-export shim） | 由 SecurityBoundaryMiddleware 注入（`agent/middlewares/security/security_boundary_middleware.py:68`）；**不占用 `messages[0]`** |

**`messages[0]` 合计（实测，含上表 1~8，不含运行时条件追加）**：

| 模型族 | full-ZH | full-EN | lean-ZH | lean-EN |
|--------|--------:|--------:|--------:|--------:|
| GPT-5 / Codex / Grok | **2,269** | 1,910 | 1,614 | 1,533 |
| Claude Sonnet / Haiku | 1,858 | 1,499 | 1,203 | 1,122 |
| Claude Opus | 2,036 | 1,677 | 1,381 | 1,300 |
| Gemini | 1,902 | 1,543 | 1,247 | 1,166 |
| DeepSeek / Qwen / GLM | 1,845 | 1,486 | 1,190 | 1,109 |

> 口径：`messages[0]` = CORE(mode, locale, `enable_answer_tool=False`) + DATETIME 89 + (AGENT_CORE_RULES 303 + TOOL_ENFORCEMENT 174) + 模型族纪律 + channel hint 56(web_chat) + env 行 43(macOS) + canary 均值 53。
> 上表按 `_ENFORCEMENT_FAMILIES` 全覆盖口径：GPT/Codex/Grok · Claude/Anthropic · Gemini/Gemma · DeepSeek/Qwen/GLM 均计入 TOOL_ENFORCEMENT；仅 Opus 额外叠加 178。若模型名不含上述族关键词，则再减 174。
> canary 为随机 hex，实测 50~57 tok（均值 53），故上表存在 **±4** 抖动；其余分量在参数组合内字节恒定。
>
> 默认组合（GPT-5 族 + 中文用户 + full）：`messages[0]` 2,269 + `messages[1]` 299 = **2,568 tokens**。
>
> **运行时条件追加**（默认不注入，按需叠加，不计入上表；均来自 `server/ai_agents/general_agent/factory.py` 的 `system_prompt +=` 分支）：
> `DESKTOP_CONTROL_RULES` 424 EN / 517 ZH（`:535`，`mount_desktop_prompt`）· `SEARCH_DEEP_SUFFIX`（`:507`，search 深研模式）· unattended 声明 ~55（`:510`）· `get_worker_lifecycle_guidance()`（`:527`，kanban worker 模式）· `get_cli_tools_context()`（`:545`，`mount_cli_context`）· `CHANNEL_NOTIFY_SYSTEM_APPENDIX`（`:554`，通知工具挂载）· `[Mounted Workspace Directories]` 清单（`:568`，session roots）· `user_instructions`（`stream_lane_factory.py:484`）。

**`enable_answer_tool` 影响**（该 flag 在 `general_agent_prompt._PROMPT_MAPS` 预构建时二分，改变 CORE 主体本身）：full 模式 EN +76 / ZH +82，lean 模式 EN +76 / ZH +82，naked / search 模式**无差异**。server 默认 `False`（`server/ai_agents/agents.py:132`），上表已按 False 计量。

**缓存特性**：`messages[0]` 与 `messages[1]` 除 canary 随机 hex（±4 tok 抖动）外均为参数组合内字节恒定，跨用户共享缓存。

---

## 二、CORE 工具层（8 个；通用 Agent Turn1 bind 8 个，shell 启用时）

> 通用 Agent 基线：`web_fetch` + file×3 + bash×2 + glob/grep（`tool_layers.py:64-71`）。Fast 模式由 `resolve_agent_mount(WEB_FAST)` 关闭 file/bash。

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 4a | web_fetch_tool | 148 | `harness/toolkits/web_fetch/web_fetch_agent_tools.py` | HTTP 抓取/深读 | Turn1 基线 |
| 6 | **bash_code_execute_tool** | **1,425** | `harness/agent/meta_tools/bash/_tool/tool_description.py` + `_tool/helpers.py:54` | Shell/Python。**宿主相关**：静态描述 1,368（宿主无关）+ OS hint（含 `os_release`/`arch`，见 `platform.py:116-122`；macOS arm64 58 / ubuntu-latest 32 / 各发行版实测 31–60）+ 可选 toolchain 探测行（干净环境为 0）。拼接处 BPE 合并使实测总数比两段之和少 1（1,368+58=1,426，实测 1,425） | 通用 Agent 基线 |
| 6b | **bash_process_tool** | **107** | `harness/agent/meta_tools/bash/bash_process_tools.py` | 后台进程 list/output/kill（CORE；与 bash_code_execute 同挂） | enable_shell_tools |
| 7 | file_edit_tool | 132 | `harness/agent/meta_tools/file_ops/file_edit_tool.py` | 批量 edits[] 原子编辑 | 通用 Agent 基线 |
| 8 | file_read_tool | 332 | `harness/agent/meta_tools/file_ops/file_read_tool.py` | 读取文件 | 通用 Agent 基线 |
| 9 | file_write_tool | 118 | `harness/agent/meta_tools/file_ops/file_write_tool.py` | 创建/覆盖写入 | 通用 Agent 基线 |
| 10 | glob_tool | 201 | `harness/agent/meta_tools/file_search/glob_tool.py` | 通配符搜索 | 通用 Agent 基线 |
| 11 | grep_tool | 205 | `harness/agent/meta_tools/file_search/grep_tool.py` | 正则搜索 | 通用 Agent 基线 |

**CORE 描述小计（Turn1）**：**2,668 tokens**（8 工具，macOS arm64 实测；`scripts/measure_turn1_token_inventory.py`）。Linux 宿主因 OS hint 更短而为 2,642（ubuntu-latest 实测）。

---

## 三、HIGH_PRIORITY 工具层（注册 5 个；高优层 · Default-ON, User-Togglable）

**架构定位**：生产级 Agent 的高优标配工具，**默认开箱即用 100% 开启（Default-ON）**，但允许用户在前端设置中按需手动关闭（User-Togglable，如无痕对话 `incognito_mode` 关闭记忆，或纯离线环境关闭网络搜索）。

默认 Turn1 bind：**web_search + memory×3 + skill_select**（`DEFAULT_ENABLED_BUILTIN_TOOLS` 含 memory；`todo_write` 与 `request_answer_user_tool` 默认不 bind，见各 opt-in 开关）。

组内排序（`get_tool_registry_sort_key`）：**web_search (Rank 0) → memory 块 (Rank 10~12) → skill_select (Rank 20)**。

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 12 | **web_search_tool** | **1,174** | `harness/toolkits/web_search/_web_search_tool_description.py` | 网络搜索（EN/ZH LLM-facing query-rewrite SSOT；server 传 locale） | GUI 可关 |
| 13 | **memory_search_tool** | **156** | `harness/toolkits/memory/_memory_agent_tool_descriptions.py` | 统一检索（corpus ACL 与 policy 一致；默认仅 memory corpus） | enable_memory |
| 14 | **memory_save_tool** | **720** | `harness/toolkits/memory/_memory_agent_tool_descriptions.py` | 写入长期记忆（EN core；wiki/approval 动态段；保留原有关键 guardrail 短语） | enable_memory |
| 15 | **memory_manage_tool** | **359** (EN) / **422** (ZH) | 同上 | 更新/删除/纠正/评分；correct→knowledge only（preserves history）；update→措辞微调；instruction→category=rule；**user-locked rule 不可 update/delete** | enable_memory |
| 16 | **skill_select_tool** | **240** (EN) / **278** (ZH) | `harness/agent/meta_tools/skills/select/skill_select_tool.py` | 字节稳定静态 rules，按 locale 选 EN/ZH 常量；bound catalog 在首条 HumanMessage `<bound_skills>` | skill_backend present |

**HIGH_PRIORITY 描述小计（Turn1，EN 描述）**：**2,649 tokens**（5 工具；web_search + memory×3 + skill_select；默认 memory_search 仅 memory corpus）

---

## 四、EXTENDED 工具层（harness 可选；EXTERNAL 在其后）

### 4.1 工作记忆手边工作台（Turn1 挂载；`enable_working_memory_tool` 默认开启）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 17 | `working_memory_manage_tool` | **51** | `harness/agent/meta_tools/working_memory/working_memory_agent_tools.py` | 多步执行的工作台：子任务状态推进、死路丢弃（自动沉淀避坑防线）、结论压缩、临时备忘 | `enable_working_memory_tool`（harness 默认 True；server 目前未暴露开关） |

参数 JSON Schema 本体约 **600 tokens**，计入 §六 全量口径。

### 4.2 glob/grep（归属 CORE 层）

glob_tool / grep_tool 登记在 CORE 层，Turn1 与 file 工具一并 bind。见 §二。

### 4.3 历史会话搜索（opt-in，由 memory_search_tool 承载）

历史聊天检索通过 `memory_search_tool` 的 `corpus=sessions` ACL 启用（用户开启 `memoryEnableConversationSearch` 且非无痕）。`conversation_search/` 模块为 sessions corpus 执行后端；`create_conversation_search_tool` 工厂仅 harness 单元测试使用，非 Turn1 LLM 工具。

### 4.3 技能工具（有技能后端时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 21 | skill_manage_tool | 251 | `harness/agent/meta_tools/skills/manage/skill_manage_tool.py` | 创建/修改/删除技能 |
| 22 | skill_search_tool | 203 | `harness/agent/meta_tools/discover_capability/discover_capability_tool.py` | 统一能力发现；**条件绑定**（hidden_skill_count > 0；tiktoken measured woven desc） |
| 23 | skill_market_tool | ~175 | `harness/agent/meta_tools/skills/market/skill_market_tool.py` | 从外部源安装/卸载技能；bound-library 提示经 dynamic_hints 条件注入 | Turn1 when market_backend present |

### 4.4 交互工具（harness 提供，按配置加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 26 | ask_question_tool | 118 | `harness/agent/meta_tools/clarification/clarification_agent_tools.py` | 结构化澄清；`requires_confirmation` 驱动危险强调；middleware 强制单轮单次 | server mount policy (interactive web_chat) |
| 27 | **request_answer_user_tool** | **1,024** | `harness/agent/meta_tools/answer_user_tool.py` | 搜索 Agent 终局自审门 | 默认关闭（`answer_tool` opt-in，EXTENDED 层） |

### 4.6 子 Agent 委托工具（有子 Agent 配置时加载；空 catalog 零 bind）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 28 | delegate_task_tool | TBD | `harness/agent/meta_tools/spawn_subagent/delegate_task_tool.py` | 统一委派（mode=single\|batch\|parallel） |
| 29 | subagent_control_tool | TBD | `harness/agent/meta_tools/spawn_subagent/agent_manage_tool.py` | 运行时控制（action=list\|cancel\|steer） |
| 30 | send_teammate_message_tool | 40 | `harness/agent/meta_tools/spawn_subagent/send_teammate_tool.py` | Orchestrator 子 Agent P2P 通信 |
| 31 | invoke_acp_agent_tool | 216 | `harness/toolkits/acp/acp_agent_tools.py` | ACP 协议 Agent 委托（有 ACP 配置时） |

### 4.7 浏览器工具（启用浏览器时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 37 | browser_navigate_tool | 18 | `harness/toolkits/browser/tools/navigate.py` | 浏览器导航 |
| 38 | browser_snapshot_tool | 115 | `harness/toolkits/browser/tools/snapshot.py` | 页面快照 |
| 39 | browser_interact_tool | 66 | `harness/toolkits/browser/tools/interact.py` | 页面交互 |
| 40 | browser_extract_tool | 95 | `harness/toolkits/browser/tools/extract.py` | 内容提取 |
| 41 | browser_inspect_tool | 82 | `harness/toolkits/browser/tools/inspect.py` | 元素检查 |
| 42 | browser_manage_tool | 171 | `harness/toolkits/browser/tools/manage.py` | 浏览器管理（含 web_vitals 性能洞察） |

### 4.8 定时任务工具（启用 Cron 时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 47 | cron_manage_tool | 827 | `harness/toolkits/cron/cron_agent_tools.py` | 定时任务管理；蓝图目录经 `action=blueprints` 按需拉取，不占 Turn1 描述 |

### 4.10 Wiki 知识库工具（有 Wiki 目录时加载）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 48 | wiki_query_tool | 33 | `harness/toolkits/wiki/wiki_agent_tools.py` | 查询 Wiki 知识库 |
| 49 | wiki_ingest_tool | 62 | `harness/toolkits/wiki/wiki_agent_tools.py` | 导入内容到 Wiki |
| 50 | wiki_apply_tool | 58 | `harness/toolkits/wiki/wiki_agent_tools.py` | 窄写更新 Wiki 词条（truth/timeline/metadata/create） |

> `wiki_compile_tool` / `wiki_maintain_tool` 仅保留在 Settings REST 与 `create_wiki_admin_tools()`，不进入 Turn1 LLM 工具集。

### 4.11 Goal / planning 工具

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 56 | complete_goal_tool | 120 | `harness/agent/meta_tools/goals/goal_agent_tools.py` | 显式声明目标完成 | active Goal |
| 57 | todo_write | ~150 | `harness/agent/meta_tools/progress/todo_write_tool.py` | 主 Agent 多步进度 | 默认关闭（`planning` / Goal） |

### 4.13 看板工具（启用看板时加载，按角色分组）

**Server bind 策略**：Chat Agent + kanban → `orchestrator` 3 工具；`KanbanTaskRunner` → `worker` 6 工具。看板/任务 CRUD 走 REST/GUI。解析：`myrm-agent-server/app/ai_agents/general_agent/kanban_tool_mode.py`。

#### Worker 工具（6 个）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 58 | kanban_show | 75 | `harness/toolkits/kanban/kanban_agent_tools.py` | 查看当前任务详情（描述/依赖/历史） |
| 59 | kanban_complete | 248 | `harness/toolkits/kanban/kanban_agent_tools.py` | 标记任务完成并提交结构化交接 |
| 60 | kanban_block | 298 | `harness/toolkits/kanban/kanban_agent_tools.py` | 阻塞任务（支持定时自动解除） |
| 61 | kanban_heartbeat | 100 | `harness/toolkits/kanban/kanban_agent_tools.py` | 报告运行中任务的进度（SSE） |
| 62 | kanban_comment | 227 | `harness/toolkits/kanban/kanban_agent_tools.py` | 跨任务评论协调（不限所有权，Worker 可评论任意任务） |
| 63 | kanban_attach | ~180 | `harness/toolkits/kanban/kanban_agent_tools.py` | 挂接沙箱文件或 HTTPS URL 到任务 |

#### Orchestrator 工具（3 个）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 64 | kanban_add_task | 616 | `harness/toolkits/kanban/kanban_agent_tools.py` | 添加新任务（depends_on/优先级/技能/幂等） |
| 65 | kanban_list_tasks | 119 | `harness/toolkits/kanban/kanban_agent_tools.py` | 列出任务；可选 `include_stats`；`task_id` 单查 |
| 66 | kanban_unblock | ~90 | `harness/toolkits/kanban/kanban_agent_tools.py` | 解除 BLOCKED 任务 |

### 4.17 桌面语义控制工具（启用 Computer Use 时加载）

`create_desktop_tools()` 定义 3 个工具（`harness/toolkits/computer_use/desktop_agent_tools.py:72/150/204`）：

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 |
|---|--------|------------------:|----------|------|
| 77 | desktop_snapshot_tool | 91 | `harness/toolkits/computer_use/desktop_agent_tools.py` | AX 树 + @dref，可选截图 |
| 78 | desktop_interact_tool | 40 | `harness/toolkits/computer_use/desktop_agent_tools.py` | @dref 语义交互（含 set_value） |
| 79 | desktop_vision_tool | 69 | `harness/toolkits/computer_use/desktop_agent_tools.py` | 显式截图/坐标回退 |

移动端镜像工具（`harness/toolkits/mobile_adb/mobile_agent_tools.py`，仅 macOS + 启用 iPhone Mirroring 场景加载）：`mobile_snapshot_tool` / `mobile_interact_tool` / `mobile_global_tool`。

### 4.18 内部分类（非 LLM 工具，默认 GeneralAgent Turn1 = 0 token）

编排信号与 runtime hook **不是 LLM 工具**，不在 `_TOOL_LAYERS`。SSOT：`agent/orchestration/`。LLM 工具清单见 `TOOL_MANAGEMENT_SYSTEM.md` 自动生成表。

| 桶 | 成员 | 说明 |
|----|------|------|
| Orchestration signal | `dispatch_research` / `think` / `finalize_report` | DR orchestrator 截获；不进 ToolNode |
| Orchestration signal | `submit_verdict` | Verifier 子 Agent 会话 |
| Runtime hook | `_completion_check` | CompletionGuard `RUNTIME_ONLY` |

PTC（`myrm_tools.spawn_subagent` / `notify`）等非 LLM 实现见 §4.25，零 Turn1 bind。

Token 明细（历史 tiktoken 计量保留）：

| # | 名称 | Token (tiktoken) | 来源 |
|---|------|------------------:|------|
| 83–85 | DR 三件套 | 37/37/26 | `orchestration/signals/deep_research.py` |
| 86 | submit_verdict | 26 | `orchestration/signals/verifier.py` |
| 87 | _completion_check | 42 | `orchestration/hooks.py` + `completion_guard.py` |

### 4.24 Server 层业务工具（server 启动时动态注册，依赖第三方 SDK）

| # | 工具名 | Token (tiktoken) | 来源文件 | 说明 | 加载条件 |
|---|--------|------------------:|----------|------|----------|
| 88 | channel_notify_tool | 333 | `server/services/agent/outbound_notify/channel_notify_tool.py` | Agent 主动 IM 出站（白名单+频控+附件） | Agent 配置 `notify_targets` 时 [Turn1] |
| 89 | image_tool | ~150 | `server/services/integrations/tools/image_generation.py` | 图像生成工具（DALL-E / SD / Flux） | enabled_builtin_tools: image_generation |
| 90 | video_tool | ~180 | `server/services/integrations/tools/video_generation.py` | 视频生成工具 | enabled_builtin_tools: video_generation |
| 91 | tts_generate | ~120 | `server/services/integrations/tools/tts.py` | 语音合成工具 | enabled_builtin_tools: tts |
| 92 | artifact_publish | ~140 | `server/services/hosting/agent_publish_tool.py` | 工件/网页在线打包与托管发布 | server 凭证就绪 |

> 注：`x-live-search` 采用 Prebuilt Skill + 沙箱标准脚本 PTC（Programmatic Tool Calling）范式，0 Action Tool 注册（Turn1 0 Token 开销，不污染 Action Space）。

### 4.25 PTC 桥接（非 LLM 工具，非 `_TOOL_LAYERS` 登记）

| 名称 | 暴露形式 | 说明 |
|------|----------|------|
| `spawn_subagent` | `myrm_tools.spawn_subagent()` | PTC 脚本内阻塞 spawn；≠ LLM `delegate_task_tool` |
| `notify` | `myrm_tools.notify()` | Workflow 阶段 SSE；0 Turn1 bind |

---

## 五、动态注入内容（~1,200 tokens，Turn 1 典型值）

| 组件 | Token (估算) | 来源 | 说明 |
|------|------------:|------|------|
| user_instructions | ~200 | `server/app/ai_agents/agent_middlewares/user_instructions_middleware.py` | 用户自定义指令（SystemMessage，注入在 system prompt 之后） |
| Memory context | ~500 | `harness/agent/middlewares/memory_context/memory_context_middleware.py` | Stable：`<user_memory_context>` **SystemMessage**；Turn1 learned 为空（检索走 `memory_search_tool`）；Learned 历史形态经 `wrap_untrusted` → HumanMessage |
| Inline skills 列表 | ~500 | 技能系统 | `<skills>` 块内联展示可用技能名+描述（取决于已安装技能数量） |

**缓存特性**：
- `user_instructions` 同用户同会话内稳定，不破坏缓存
- `Memory context` 同用户连续对话内 stable 段稳定；learned 不在 Turn1 注入（由 tool 检索）
- `Inline skills` 同用户同技能配置内稳定

---

## 六、格式开销（~2,900 + 参数 schema ~4,400 ≈ **~7,300 tokens**，模型/API 相关）

| 组件 | Token (估算) | 说明 |
|------|------------:|------|
| 工具参数 schema | ~338/tool | 参数 JSON Schema 本体；`estimate_bound_tools_tokens` 不含此项，仅 `measure_tool_schema_tokens.py` 全量口径统计 |
| schema wrapper 包装 | ~65/tool | 每个工具 API 格式的**包装**开销（function name、schema 外壳等），**不含参数 schema**；参数 schema 见上一行 |
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

### 典型 Turn 1 场景（默认智能体，记忆+搜索+技能+工作台；无 answer/todo）

| 分类 | Token (tiktoken) | 明细 |
|------|------------------:|------|
| System Prompt 层 | **2,568** | `messages[0]` 2,269（GPT-5 族 · ZH · full）+ `messages[1]` 299，固定，跨用户缓存 |
| CORE 工具层 | **2,668** | 8 工具描述（含 bash_process；`measure_turn1_token_inventory.py` 实测，o200k_base） |
| HIGH_PRIORITY 工具层 | **2,649** | web_search + memory×3 + skill_select |
| EXTENDED 工具层 | **51** | working_memory_manage_tool（`enable_working_memory_tool` 默认开启） |
| schema wrapper 包装 | **910** | 14 工具 × 65（仅 API 包装，不含参数 schema） |
| 动态注入 | ~1,200 | user_instructions + memory_context + inline_skills |
| 消息格式 | ~500 | role tags, boundaries 等 |
| 用户消息 | ~32 | 短消息 + datetime 标签 |
| **tiktoken 小计** | **~10,578** | |

### 最小 Turn 1 场景（仅 CORE 8 工具，无 HIGH_PRIORITY/EXTENDED）

| 分类 | Token (tiktoken) |
|------|------------------:|
| System Prompt 层 | **2,568** |
| CORE 工具层 | **2,668** |
| schema wrapper 包装 | **520** (8 工具 × 65) |
| 用户消息 | ~32 |
| 消息格式 | ~300 |
| **tiktoken 小计** | **~6,088** |

### 满载场景（所有可选功能全开：浏览器+Cron+Wiki+子Agent+渲染UI+看板+日历+计算机+IM）

| 分类 | Token (tiktoken) |
|------|------------------:|
| System Prompt 层 | **2,568** |
| CORE 工具层 | **2,668** |
| HIGH_PRIORITY 工具层 | ~2,649 |
| EXTENDED + EXTERNAL（42 + 7 = 49 工具） | ~7,400（**粗估，未逐项实测**；EXTENDED 装配依赖各 backend，无法在离线脚本中全量构建） |
| schema wrapper 包装 | ~3,185 (49 工具 × 65) |
| 动态注入 | ~1,200 |
| 消息格式 | ~500 |
| **tiktoken 小计** | **~20,072（粗估）** |

> 工具数量以文件末尾 `TOOL_COUNT_BEGIN/END` 自动生成块为 SSOT（当前 62 LLM 工具 = CORE 8 + HIGH_PRIORITY 5 + EXTENDED 42 + EXTERNAL 7）。本场景假设全部 62 工具同轮 bind；EXTENDED/EXTERNAL 描述 token 未逐项实测，仅作量级参考。

---

## 缓存分层效果

```
[CORE: web_fetch + bash + file_* + glob + grep (~2,668 tok, 8 tools)]
  ↑ 通用 Agent 基线前缀（agent 模式）

[HIGH_PRIORITY: web_search + memory_* + skill_select (~2,649 tok)]
  ↑ web_search 优先；memory 组紧随；skill_select 承接；GUI 可关

[EXTENDED: working_memory_manage_tool (51) + 可选工具 (~0~7,411 tok)]
  ↑ 按需变化，不影响 CORE/HIGH_PRIORITY 前缀

[System Prompt: messages[0] 2,269 (GPT-5·ZH·full) + messages[1] 299]
  ↑ 冻结，跨用户共享缓存

[Dynamic: user_instructions(~200) + memory_context(~500) + skills(~500)]
  ↑ 同用户会话内稳定
```

**实测 Turn1 工具层合计**：描述 **5,304** + schema wrapper **845** = **6,149 tokens**（13 工具，`measure_turn1_token_inventory.py`，o200k_base，macOS arm64 宿主）。Linux 宿主因 bash OS hint 更短而为 6,123。

> **口径边界（重要）**：`6,149` 为「描述 + wrapper 包装」口径，**不含工具参数 schema**。参数 schema 是真实发送给模型的 payload 一部分，全量口径见 `measure_tool_schema_tokens.py`（其 `Total Budget` = 描述 **5,304** + 参数 schema **4,400** + wrapper **845** = **10,549**）。下方各 Turn-1 场景表的「schema wrapper 包装」行与 harness 门禁阈值均沿用「描述 + wrapper」口径，与 `estimate_bound_tools_tokens`（`utils/token_estimation.py:117-120`）一致；该估算仅用于展示与预检，压缩与预算决策以 provider 实测 `prompt_tokens` 为准（`estimate_context_tokens` 取 `max(estimate, provider)`）。

**CI 门禁（横跨 harness / server 两仓）**：

| 仓 | 门禁文件 | 锁定项 |
|----|----------|--------|
| harness | `tests/architecture/test_prompt_token_budget_gate.py` | Turn-1 默认工具集 ≤ **6,500**（当前 6,149，余量 351；口径=描述+wrapper，**不含参数 schema**）；`AGENT_CORE_RULES` ≤ 350 / `SECURITY_BOUNDARY_SYSTEM_RULES` ≤ 350 / `DATETIME_SYSTEM_RULES` ≤ 120；SystemMessage 哈希跨调用恒定 |
| harness | `tests/scripts/test_measure_turn1_token_inventory.py` | 逐工具描述 token 与 §二/§三 表格一致（漂移即失败并指出工具名）；`bash_code_execute` 的宿主相关 OS hint 单独扣减，故 macOS 与 Linux CI 结果一致 |
| server | `tests/ai_agents/test_prompt_integrity.py:187-224`（`cl100k_base`） | CORE full ≤ **2,000** / lean ≤ **1,200** / lean÷full ratio ≤ **0.70** |


---

## 工具层级注册表 (tool_layers.py)

<!-- TOOL_COUNT_BEGIN -->
LLM tools: **62** (Harness 55: CORE 8 + HIGH_PRIORITY 5 + EXTENDED 42; External 7: server vendor). Orchestration signals: **4**. Runtime hooks: **1**. PTC runtime tools: **6** (`human_ask`, `llm_query`, `llm_query_batched`, `notify`, `spawn_subagent`, `steer_child`). LLM-tool SSOT: `tool_layers.py` + `_tool_layer_bootstrap.py`. PTC SSOT: `agent/dynamic_workflow/tools.py` + `PTC_RUNTIME_TOOL_NAMES`. Orchestration SSOT: `agent/orchestration/`. Auto-generated by `scripts/validate_tool_registry.py --generate-docs`.
<!-- TOOL_COUNT_END -->
未注册的工具（如 MCP 动态工具）自动归入 EXTENDED，并在运行时打印 WARNING 日志。
完整列表请直接查看 `tool_layers.py`。
