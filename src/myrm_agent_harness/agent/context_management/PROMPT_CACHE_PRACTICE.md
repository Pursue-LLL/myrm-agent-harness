# Prompt Cache 实践：框架的真实应用与实现

>
> | 章节 | 关联源代码 |
> |------|-----------|
> | §2.1 工具分层排序 | `tool_management/tool_layers.py`, `tool_management/registry.py` |
> | §2.2 时间戳注入 & Agent 行为规则 | `streaming/utils.py`, `base_agent.py` |
> | §2.3 Cron 场景 | `app/core/cron/adapters/agent_runner.py` |
> | §2.4 安全边界与用户指令注入 | `app/ai_agents/agent_middlewares/user_instructions_middleware.py` |
> | §2.5–2.6 记忆 / 入账 Human 前缀 | `middlewares/memory_context_middleware.py`；`delivery_provenance.py`、`channels/agent_executor/helpers.py`、`general_agent/stream_pipeline.py`、`api/agents/general_agent/streaming.py`、`services/agent/wakeup_handler.py`、`fast_search_agent/agent.py` |
> | §3 显式缓存优化器 | `pipeline/processors/cache_optimizer.py` |
> | §4.1 批量清理 | `pipeline/processors/compress_processor.py` |
> | §4.2 compress_min_save | `schemas.py` |
> | §4.3 动态阈值 | `infra/context_budget.py` |
> | §4.4 可逆压缩 | `strategies/compactor.py` |
> | §4.5 摘要与缓存生命周期 | `strategies/summarizer.py` |
> | §5.1 Cache-TTL 归档与恢复 | `pipeline/processors/cache_ttl_prune_processor.py`, `infra/archive_reference.py`, `tracking/task_metrics.py`, `meta_tools/file_ops/core/file_operation_service.py` |
> | §5 Pipeline | `pipeline/engine.py`, `middlewares/context_pipeline_middleware.py` |
> | §6.1-6.2 LLM 层 | `toolkits/llms/llm.py` |
> | §6.3 缓存可观测性 | `utils/token_economics/tracker.py`, `toolkits/llms/utils/logger.py` |
> | §6.3 层次5 缓存断裂诊断 | `infra/cache_break_detector.py`, `infra/cache_metrics_collector.py` |

本文档记录 myrm-agent-harness 框架对 Prompt Cache 的真实实践和应用。
与 [CONTEXT_ENGINEERING.md](./CONTEXT_ENGINEERING.md) 的业界理论对照，本文聚焦于**框架代码中的具体实现**。

---

## 目录

1. [整体策略](#1-整体策略)
2. [前缀稳定性保障](#2-前缀稳定性保障) — 工具分层排序、时间戳注入、用户指令注入、记忆上下文注入
3. [显式缓存优化器](#3-显式缓存优化器) — ExplicitCacheProcessor 断点策略
4. [缓存友好的上下文缩减](#4-缓存友好的上下文缩减) — 批量清理、compress_min_save、动态阈值、缓存生命周期
5. [Pipeline 架构与缓存协同](#5-pipeline-架构与缓存协同) — 处理器执行顺序与缓存感知
6. [LLM 层集成](#6-llm-层集成) — cache_control 传递链路、缓存可观测性（四层监控）、性能特性
7. [故障排查指南](#7-故障排查指南) — 常见问题诊断与解决方案
8. [代码索引](#8-代码索引)

---

## 1. 整体策略

框架采用**双层优化**架构，与 Manus 的设计理念一致：

```
缓存层（成本优化）                     质量层（上下文管理）
├─ 工具分层排序 (ToolLayer)            ├─ Filter（立即、可逆）
├─ System Prompt 冻结                  ├─ Compress（批量、可恢复）
├─ 时间戳注入到 HumanMessage           ├─ Summarize（最后手段、不可逆）
├─ 只增不改的消息历史                   └─ ThinkingBlockCleaner（清理无效 token）
├─ 显式 cache_control 断点
└─ 批量清理（积累-爆发模式）
```

**核心指标**：KV Cache 命中率。框架的每一个设计决策都围绕"不破坏前缀"展开。

---

## 2. 前缀稳定性保障

LLM API 的序列化顺序为 `Tools → System Prompt → Messages`。前缀匹配是 token 级别的——修改靠前的内容会使后续所有缓存失效。框架从三个维度保障前缀稳定。

### 2.1 工具分层排序（ToolLayer + ToolRegistry）

**理论依据**：工具定义位于序列化最前端，任何变化都会使全部缓存失效。

**实现**：

`tool_layers.py` 定义三层枚举：

```python
class ToolLayer(IntEnum):
    CORE = 1       # 始终存在，不可关闭
    COMMON = 2     # 默认存在，前端可控制开关
    EXTENDED = 3   # 按需加载
```

具体的工具层级注册：

| 层级 | 工具 | 常驻理由 |
|------|------|---------|
| **CORE** | （无 unconditional 工具） | 登记层为空 | — | `web_fetch_tool` 在 COMMON，随 web 组加载 |
| **COMMON** | `request_answer_user_tool`, `bash_code_execute_tool`, `file_edit_tool`, `file_read_tool`, `file_write_tool`, `todo_write`, `web_search_tool` | 注册 7 个；默认 profile bind 5 个（answer/todo_write 由 Agent 配置 / Goal / workspace todos 按需加载） |
| **EXTENDED** | 83 个注册工具（浏览器/记忆/技能/Sub-Agent/…）+ 动态 MCP | 按需加载或始终加载的辅助工具 |

`ToolRegistry.resolve()` 执行去重 + 排序：

```python
sorted_entries = sorted(
    best.values(),
    key=lambda e: (e.layer or ToolLayer.EXTENDED, e.tool.name),
)
```

排序规则：先按层级（CORE → COMMON → EXTENDED），同层级内按名称字母序。

**缓存效果**：

```
第 1 轮: [CORE: web_fetch][COMMON: request_answer_user,bash,file_edit,file_read,file_write,planner,web_search][EXTENDED: skill_select][Messages...]
第 2 轮: [CORE: web_fetch][COMMON: request_answer_user,bash,file_edit,file_read,file_write,planner,web_search][EXTENDED: memory_recall_tool][Messages...]
         |<────────────────────────────────── 这部分始终缓存命中 ──────────────────────────────────>|
```

即使 EXTENDED 层工具变化，CORE + COMMON 的缓存仍然有效。

### 2.2 System Prompt 冻结 + 时间戳注入到 HumanMessage

**理论依据**：在 System Prompt 中放入 `datetime.now()` 是最常见的缓存破坏原因。

**实现**：采用两层分离设计：

1. **System Prompt（框架层自动追加）**：`streaming/utils.py` 定义 `DATETIME_SYSTEM_RULES` 常量，`base_agent.py` 在 `_ensure_initialized()` 中自动追加到 system_prompt 末尾，业务层无需感知：

```xml
<datetime_rules>
Messages may contain timestamp tags: `[Sent at: YYYY-MM-DD HH:MM Weekday (UTC±X)]` for historical messages (immutable, preserves Prompt Cache), or `<current_datetime>YYYY-MM-DD HH:MM:SS Weekday (UTC±X)</current_datetime>` for the current message. Always use the latest `<current_datetime>` as your only "now" reference for all time-related reasoning.
</datetime_rules>
```

2. **HumanMessage（`streaming/message_builder.py`）**：语义分离标签

```python
# 历史消息：[Sent at: 2026-04-13 17:13:38 Monday (UTC+8)]
# 输出示例：[Sent at: 2026-03-09 10:30 Sunday (UTC+8)]
prompt = f"[Sent at: {format_time_with_timezone(dt, sent_timezone)}]"

# 当前消息：<current_datetime>2026-03-09 10:30:22 Sunday (UTC+8)</current_datetime>
prompt = get_datetime_prompt(current_timezone)
```

`message_builder.py` 中将时间戳注入到 **HumanMessage**，使用不同标签区分语义：

```python
# 当前消息：使用 <current_datetime> 标签
messages[-1] = HumanMessage(content=f"{query}\n\n{datetime_prompt}")

# 历史消息：使用 [Sent at: ...] 标签，确保缓存稳定
dt = datetime.fromtimestamp(sent_at, tz=UTC)
time_str = format_time_with_timezone(dt, sent_timezone)
prompt = f"[Sent at: {time_str}]"
messages[idx] = HumanMessage(content=f"{msg.content}\n\n{prompt}")
```

**关键设计**：

- **历史消息使用确定性时间戳**：同一 `ts + UTC offset` 永远产生相同输出，保证历史部分前缀 100% 命中
- **仅最后一条消息（新内容）无法缓存**——这是不可避免的
- **System Prompt 永远不包含动态内容**——完全冻结
- **说明文案与数据分离**：`datetime_rules` 在 System Prompt 中声明一次（被缓存），每条消息只携带 ~12 tokens 的时间戳数据，相比每条重复完整说明节省 ~28 tokens/条
- **执行纪律系统**：`resolve_execution_discipline(llm)`（`streaming/model_discipline.py`）追加在 `DATETIME_SYSTEM_RULES` 之后、`canary_instruction` 之前。输出固定文本（由模型名称决定，session 内不变），完全缓存安全。包含三层：Layer 1 核心规则（反叙述 + 工具诚实），Layer 2 工具强制（必须行动而非描述），Layer 3 per-model 纪律（GPT/Gemini/Claude/DeepSeek 等各有针对性纠正）
- **环境感知注入**：`detect_platform().environment_prompt_line`（`toolkits/code_execution/platform.py`）追加在 `resolve_channel_output_hint` 之后。输出一个 `<environment>` XML 标签，包含 OS 类型/版本/架构、Shell 类型/工具链差异、Python 工具链状态（pip/PEP-668/uv）。由 `detect_platform()` 的 `@lru_cache(maxsize=1)` 保证进程生命周期内不变，Python 探测由 `env_probe.get_environment_probe_line()` 的 `threading.Lock` 保证一次性探测。正常环境省略 Python 部分（零额外 token），异常环境增加 <50 tokens。完全缓存安全

这与 Claude Code 的官方策略一致：动态信息通过 `<system-reminder>` 标签放在 user message 中。

**已知边缘情况 — Timezone 切换**：历史消息的时间戳使用**当前请求时的用户时区**渲染（`user_timezone_var.get()`）。如果用户在对话中途切换时区（如 `Asia/Shanghai` → `America/New_York`），同一条历史消息的 UTC offset 会变化（`UTC+8` → `UTC-5`），导致该消息之后的前缀缓存一次性失效。

这是有意的取舍：优先保证 LLM 看到用户当前时区的本地时间（功能正确性），接受极低频的缓存失效（用户很少在对话中途切换时区）。

### 2.3 Cron 定时任务场景的缓存分析

`app/core/cron/adapters/agent_runner.py` 中的 `_SILENT_SUFFIX` 是一个典型的条件性内容注入：

```python
_SILENT_SUFFIX = (
    "\n\n---\n"
    "[Scheduler] This is a recurring scheduled task. "
    "If there is nothing actionable or noteworthy to report, "
    "respond with exactly `[SILENT]` (no other text) to skip notification delivery."
)

def _build_effective_prompt(job: CronJob) -> str:
    prompt = job.prompt or ""
    if job.schedule.kind in (ScheduleKind.CRON, ScheduleKind.INTERVAL):
        return prompt + _SILENT_SUFFIX
    return prompt
```

**缓存影响分析**（以每小时执行的 "检查服务器状态" 任务为例）：

```
第 1 次执行（10:00）：
[Tools: bash_code_execute_tool, file_read_tool, ...]                       ← 缓存命中 ✅
[System Prompt: 你是一个专业的 AI 助手...]                      ← 缓存命中 ✅
[HumanMessage: 检查服务器状态\n---\n[Scheduler]...[SILENT]
  <current_datetime>2026-03-09 10:00</current_datetime>]

第 2 次执行（11:00）：
[Tools: bash_code_execute_tool, file_read_tool, ...]                       ← 缓存命中 ✅
[System Prompt: 你是一个专业的 AI 助手...]                      ← 缓存命中 ✅
[HumanMessage: 检查服务器状态\n---\n[Scheduler]...[SILENT]
  <current_datetime>2026-03-09 11:00</current_datetime>]      ← 只有时间变了
```

| 部分 | 缓存命中？ | 原因 |
|------|-----------|------|
| Tools 定义 | ✅ | 完全不变 |
| System Prompt | ✅ | 冻结，不含动态内容 |
| `_SILENT_SUFFIX` | ✅ | 确定性常量，每次相同 |
| `<current_datetime>` | ❌ | 时间变化（不可避免） |

`_SILENT_SUFFIX` 是缓存安全的——它是确定性常量且位于 HumanMessage 中。如果把它放在 System Prompt 中，当任务类型从 `CRON` 变为 `ONCE`（无后缀）时，System Prompt 变化会导致后续所有缓存失效。

### 2.4 用户指令注入位置的缓存感知设计

`user_instructions_middleware.py` 将用户自定义指令注入为 SystemMessage。注入位置对跨用户缓存至关重要：

**设计**：注入到第一个 SystemMessage（system prompt）**之后**，而非之前。

```python
def _find_system_insert_idx(messages):
    for i, msg in enumerate(messages):
        if isinstance(msg, SystemMessage):
            return i + 1
    return 0
```

**缓存效果**：

```
[0] SystemMessage: system prompt          ← 跨用户缓存命中 ✅
[1] SystemMessage: <user_instructions>    ← 同用户缓存命中 ✅
[2] SystemMessage: <workspace_context>    ← 同 workspace 缓存命中 ✅
[3] SystemMessage: Stable `<user_memory_context>` ← 同用户缓存命中 ✅
[4] HumanMessage（可选）: <<<UNTRUSTED_DATA>>> learned advisory ← envelope id random / per-request
[5] HumanMessage: ...                     ← 每轮变化
```

如果 `user_instructions` 在 system prompt **之前**（`insert(0, ...)`），不同用户的前缀从第一个 token 就不同，system prompt 的跨用户缓存完全失效。

### 2.5 记忆上下文注入的缓存感知设计

`memory_context_middleware.py`（`asyncio.gather` 静态 + learned）拆分注入：**Stable** vs **learned advisory**。

1. **Stable** (`# User Context (stable)`)：`SystemMessage`，包裹 `<user_memory_context>`。含 Profile/Rules/Self-Instructions/Corrections；插入在连续 leading **SystemMessage** 链末端（与同用户前缀稳定对齐）。
2. **Learned advisory**：偏好与 learned rules：`HumanMessage`，在**第一条真人用户 Human** 之前插入。原始 Markdown 先做 `sanitize` + `_escape_xml_item`，再 **`wrap_untrusted(..., source="memory_context")`** → ``<<<UNTRUSTED_DATA id="random">>>`` ，与同进程 **`SECURITY_BOUNDARY_SYSTEM_RULES`** 中约定的边界语义一致。**随机边界 id**会降低「整块 HumanMessage 前缀」在厂商缓存中的可预见性——这是与安全边界预测的显式权衡；跨用户仍可共享第一条 core System Prompt 快照。

**冷/暖启动自适应**：新用户仅注入 `_COLD_START_CONTEXT`（Stable SystemMessage）；老用户 Stable + Learned Human（若有）。

**RecallMode 控制**：`TOOLS` 模式跳过注入；`CONTEXT` / `HYBRID` 正常注入。

前缀示意：

```
System: core prompt
System: `<data_boundary_rules>` …               ← SecurityBoundary
System: `<user_instructions>` …
System: `<workspace_context>` …                 ← per-workspace Stable（可无）
System: `<user_memory_context>` … stable …    ← per-user Stable
Human: <<<UNTRUSTED_DATA>>> learned …         ← advisory（可无）
Human: 用户第一句 …                             ← varies
```

**关键设计**

- **统一预算**：Stable + Learned 共享单一 `_partition_budget_sections`（max_tokens≈等价于单次 `PromptBudgetGuard(2500)`），禁止两侧各跑一次 2500 导致前缀膨胀双倍。
- **一次性注入**：同时检测 `<user_memory_context` **与** `<<<UNTRUSTED_DATA`（cover learned-only）。
- **`MemoryConfig.max_learned_context_chars`**：依旧在 learned 数据源侧裁剪；中间件再做 token/char envelope 兜底。

**业务侧入账 Human 前缀（IM + pipeline）**：`myrm-agent-server/app/core/utils/delivery_provenance.py` 提供统一横幅与 `resolve_general_agent_pipeline_labels`。IM 仍由 `app/core/channel_bridge/agent_executor/helpers.py::build_channel_inbound_query` 调用 `prepend_plain_banner`（支持多模态图片+文本）。HTTP/SSE `/agent-stream` LangGraph 主路径在 `general_agent/stream_pipeline.py::execute_stream_pipeline` **进入 `SkillAgent.run` 之前**：先 **INFO `general_agent_delivery_labels`**（`channel_label`/`ingress_label`），再 **`apply_delivery_banner`**；其中 `GeneralAgent.channel_name=="web_chat"` 仍等价 `http_gui`/`browser_sse`，`cron`/`eval`/`headless_wakeup` 等由其映射。**Headless wakeup** 在 `app/services/agent/wakeup_handler.py` 显式改写 `channel_name=headless_wakeup` 并在 `memory_channel_id` 缺省时 **写回 `web_chat`**，以免记忆分区随投递前缀漂移。FastLane/DeepResearch 在 `api/agents/general_agent/streaming.py` 使用 `apply_general_agent_pipeline_banner` + `GeneralAgentParams.channel_name`；`FastSearchAgent` 默认等价 `web_chat` 并把 `workspaces_storage_root` 写入 `context`。群组上下文块仍仅在 IM executor 拼接。

### 2.6 只增不改的消息历史

框架遵循"只追加不修改"原则：

- **压缩**使用紧凑格式**替换**工具结果内容，但不删除消息——消息结构（类型、顺序）保持不变
- **摘要**是唯一会改变消息结构的操作，作为最后手段触发
- 历史消息的时间戳一旦注入就不再修改（确定性注入）

---

## 3. 显式缓存优化器

### 3.1 适用范围

`ExplicitCacheProcessor`（`pipeline/processors/cache_optimizer.py`）只处理需要显式 `cache_control` 标记的模型：

| 模型 | 是否处理 | 原因 |
|------|---------|------|
| Anthropic Claude | ✅ | 需要显式 `cache_control` |
| 阿里云 Qwen/DashScope | ✅ | 需要显式 `cache_control` |
| OpenAI GPT | ❌ | 自动前缀缓存 |
| DeepSeek | ❌ | 自动前缀缓存 |
| Google Gemini | ❌ | 自动前缀缓存 |

模型识别逻辑：

```python
def _needs_explicit_caching(self, model_name: str) -> bool:
    model_lower = model_name.lower()
    prefixes = ("anthropic/", "claude-", "qwen", "dashscope/", "openai/qwen")
    return any(model_lower.startswith(p) for p in prefixes)
```

### 3.2 四种断点策略

基于 Anthropic 官方文档的最佳实践：

```
断点位置 = {
    1. 第一个 System 消息后（必须） → 缓存系统提示词（跨用户共享）
    2. 每 15 content blocks（自动） → 防止超出 20-block lookback window
    3. 压缩边界后（按需）           → 保护压缩内容
    4. 最后一条消息（必须）         → 增量对话缓存（官方推荐核心）
}
```

**System 断点设在第一个 SystemMessage 的设计决策**：在 Sandbox 多用户场景下，消息结构为 `[system_prompt, user_instructions, memory_context, ...]`。断点设在第一个 SystemMessage（system prompt）而非最后一个，确保 system prompt 的缓存快照可被所有用户共享。如果设在最后一个 SystemMessage（memory_context），缓存快照会包含 per-user 内容，无法跨用户复用。

**20-block 保护**：Anthropic 系统只向前查找 20 个 content blocks。框架按**实际 content blocks 累积**计数（而非消息索引），每累积 15 blocks 设置一个保护性断点，预留 5 blocks 安全余量。

关键：一条 AIMessage 带 3 个 tool_use 产生 4 个 content blocks（1 text + 3 tool_use），而非 1 个。`_estimate_content_blocks()` 精确估算每条消息的 blocks 数，确保在工具密集场景下断点间距不超过 20 blocks。

**压缩边界感知**：当 `CompressProcessor` 执行压缩后，会在 `context.metadata["last_compress_boundary_index"]` 记录边界位置，`ExplicitCacheProcessor` 据此在压缩边界后设置断点，保护压缩后的内容。

### 3.3 智能断点保留

Anthropic/阿里云限制最多 4 个断点。当对话超长时，生成的断点可能超过 4 个。

保留策略：

```
预计断点: [0:System, 16, 32, 48, 64, 74:最后]

智能保留（最多 4 个）:
实际断点: [0:System, 16, 32, 74:最后]
          └────必须保留────┘  └──必须保留──┘
```

规则：
1. **System（第一个）**：永远保留 → 缓存系统提示词
2. **最后消息**：永远保留 → 增量缓存核心
3. **中间断点**：保留前 `max_breakpoints - 2` 个

最后消息的断点即使距离不足 `min_message_gap` 也无条件保留——丢失它会导致增量缓存完全失效。

### 3.4 断点间距离验证

#### Token 精确验证

框架使用实际 token 计算验证断点间距离，确保符合 Anthropic 1024 tokens 最小要求。

**实现方法**：

```python
# cache_optimizer.py
ANTHROPIC_MIN_CACHEABLE_TOKENS = 1024

# 计算区间 tokens
segment_tokens = estimate_messages_tokens(messages[prev_bp : curr_bp + 1])

if segment_tokens >= ANTHROPIC_MIN_CACHEABLE_TOKENS:
    validated.append(curr_bp)  # Token 距离充足，保留
elif message_gap >= self.min_message_gap:
    validated.append(curr_bp)  # Fallback: 消息数满足最小间隔
```

**设计理由**：
- **精确计算**：工具调用消息可能包含 5000+ tokens，实际计算避免估算误差
- **Fallback 策略**：短消息密集场景，消息数满足最小间隔时保留断点，防止超出 20-block lookback window
- **最后消息特殊处理**：无条件保留，即使距离不足（增量缓存核心）

#### 可观测性：预期缓存统计

框架计算预期可缓存的 tokens 数，用于日志输出：

```python
# 从开始到最后一个断点的所有消息
expected_cacheable_tokens = estimate_messages_tokens(messages[: last_breakpoint + 1])
total_estimated_tokens = estimate_messages_tokens(messages)

# 计算预期命中率
expected_hit_rate = expected_cacheable_tokens / total_estimated_tokens
```

日志输出示例（简洁格式）：
```
📊 [ExplicitCache] Breakpoints: 4 at [0, 15, 30, 45] | Expected Cache: 85%
```

### 3.5 cache_control 注入

在消息的 `additional_kwargs` 中注入标记，TTL 策略根据端点自动解析：

```python
# Anthropic 直连 / Google Vertex → 1h TTL（长任务执行不会因 5min 过期而 cache miss）
msg.additional_kwargs["cache_control"] = {"type": "ephemeral", "ttl": "1h"}

# 代理 / 未知端点 → 默认 5min TTL（保守策略，避免不兼容）
msg.additional_kwargs["cache_control"] = {"type": "ephemeral"}
```

**TTL 解析优先级**：
1. `metadata["cache_retention"] = "long"` → 强制 1h TTL（业务层显式配置）
2. `metadata["cache_retention"] = "none"` → 默认 5min
3. `metadata["base_url"]` 包含 `api.anthropic.com` 或 `aiplatform.googleapis.com` → 1h TTL
4. `base_url` 为空 + `model_name` 以 `anthropic/` 开头 → 1h TTL（LiteLLM 直连路由推断）
5. 其他 → 默认 5min（保守策略）

注入前会创建消息副本，避免修改原始消息。

---

## 4. 缓存友好的上下文缩减

上下文缩减（Filter/Compress/Summarize）是必要的，但每次缩减都可能破坏缓存前缀。框架通过多种机制平衡缩减需求与缓存保护。

### 4.1 批量清理策略（积累-爆发模式）

**问题**：每次超过阈值就压缩，频繁破坏缓存。

**实现**：`CompressProcessor` + `BatchCompactState`（`compress_processor.py`）

```python
@dataclass
class BatchCompactState:
    rounds_accumulated: int = 0
    is_accumulating: bool = False
```

三阶段清理逻辑：

| 阶段 | 条件 | 行为 |
|------|------|------|
| 正常 | `tokens < dynamic_threshold` | 正常运行，重置积累 |
| 积累 | `dynamic_threshold ≤ tokens < force_threshold` | 积累轮数 +1；达到 `compress_batch_rounds`（默认 5）后批量清理 |
| 强制 | `tokens ≥ force_threshold` | 立即强制清理（安全阀） |

**会话隔离**：使用 `contextvars.ContextVar` 实现每个会话独立的积累状态。

**成本效果**：批量清理相比渐进式清理可节省约 44%（详见 CONTEXT_ENGINEERING.md §4.2）。

### 4.1.1 Anti-Thrashing 保护

**问题**：当上下文内容本身难以压缩时（如最近的工具调用都在保护范围内），压缩每次只能节省 <10%，却每次都破坏 Prompt Cache。

**实现**：`CompressProcessor`（`compress_processor.py`）通过 `TaskMetrics.compression_ineffective_streak` 追踪连续无效压缩次数（持久化在 `TaskMetrics` 中，跨 turn 累积）。

| 条件 | 行为 |
|------|------|
| `streak < 2` | 正常执行压缩 |
| `streak >= 2` 且 `tokens < 90%` | 跳过压缩，保护 Prompt Cache |
| `streak >= 2` 且 `tokens >= 90%` | 强制压缩（安全网，防止 OOM） |
| 某次压缩节省 `>= 10%` | 重置 streak 为 0 |

**与 Hot Cache Bypass 互补**：Hot Cache Bypass 保护「短时间内」的缓存（5 分钟窗口），Anti-Thrashing 保护「压缩效果差」时的缓存。两者覆盖不同场景，共同最大化 Prompt Cache 命中率。

### 4.2 compress_min_save 保护

**理论依据**：小清理节省的 token 可能不足以弥补缓存失效的成本。

**公式**（简化）：执行压缩当且仅当 `T_cleared > T_prefix × (1 - P)`

**实现**：`schemas.py` 中定义默认值：

```python
COMPRESS_MIN_SAVE_DEFAULT: int = 3000
# 假设 T_prefix=30k，按 90% 折扣估算：30k × 0.1 = 3k
```

`compactor.py` 中的检查：

```python
if potential_saved < min_save_threshold:
    logger.warning(f"[压缩] 预计节省 ({potential_saved}) < 最小阈值 ({min_save_threshold})，跳过")
    return messages, 0
```

### 4.3 动态阈值

`ContextBudget`（`infra/context_budget.py`）根据运行时状态动态调整阈值：

**动态 compress_min_save**（根据剩余空间）：

| 剩余空间 | compress_min_save 调整 | 策略 |
|---------|----------------------|------|
| > 50% | 100%（默认值） | 保守，保护缓存 |
| 20-50% | 60% | 适度激进 |
| 10-20% | 40% | 激进清理 |
| < 10% | 20%（最低 500） | 紧急模式 |

**动态 compress_threshold**（根据会话进度）：

```python
def calculate_dynamic_thresholds(self, turn_count, estimated_remaining_turns=10):
    # 计算"紧张度" = 剩余空间 / 预估需要
    urgency = remaining_tokens / estimated_remaining_tokens

    if urgency > 2.0:    # 很宽松 → 使用默认阈值
    elif urgency > 1.0:  # 中等 → 降低到 80%
    elif urgency > 0.5:  # 紧张 → 降低到 60%
    else:                # 非常紧张 → 降低到 50%
```

**设计意图**：长对话提前触发压缩，避免积累过多后一次性大规模压缩（破坏大量缓存）。

### 4.4 压缩的可逆设计（遮罩而非删除）

`compactor.py` 将工具结果替换为紧凑格式，但**不删除消息**：

```
COMPACTED: web_search_tool
QUERY: Claude API pricing 2024
FILE: /workspace/.context/compacted_web_search_tool_20241220_153000_abc123.txt
RECOVER: cat /workspace/.context/... with bash_code_execute_tool
META: tokens_saved=5000 time=2024-12-20T15:30:00
```

**Tokens vs Blocks**：压缩替换了消息内容（tokens 大幅减少），但不删除消息对象。一条 ToolMessage 压缩前后都是 1 个 `tool_result` content block。因此**压缩减少 tokens，不减少 content blocks 数**。这意味着即使压缩触发，20-block 保护断点的间距计算仍然需要精确的 blocks 计数。

**缓存影响**：紧凑格式替换了消息内容，会破坏该消息之后的缓存。但由于：
1. 批量清理减少了破坏频率
2. compress_min_save 确保每次破坏都值得
3. 消息结构不变（类型、顺序），前面的缓存不受影响

### 4.5 摘要、Session Notes 与缓存生命周期 (Context Compaction)

摘要（Summarize）和 Session Notes 是改变消息结构的操作，作为**缓存重置事件**。框架在阈值触发时执行 **上下文压缩 (Context Compaction)**，包含 U 型记忆保护与显式界定。

**触发机制**：
- **主动拦截**：到达主动健康阈值 `proactive_reset_threshold`（默认 Max 的 40%，最小 2万 Token；可通过 `ContextConfig.compress_start_ratio` 由 Agent 配置自定义，有效范围 [0.20, 0.85]）时触发。
- **Session Notes 触发**：当后台异步生成的 Session Notes 达到阈值就绪时，零 API 触发压缩。

**U 型记忆保护与缓存重建（适用于 Summarize 和 Session Notes）**：
```
摘要前（47 blocks）：                    摘要后（~10 blocks）：
[0] System prompt                       [0] System prompt (受保护，永久存在)
[1] user_instructions                   [1] user_instructions (受保护)
[2] memory_context                      [2] memory_context (受保护)
[3] First HumanMessage                  [3] First HumanMessage (受保护)
[4] First AIMessage                     [4] First AIMessage (受保护)
[5-40] 历史消息（多轮对话）              [5] <memory-context> 系统汇总摘要（替换了 [5-35]）
[41] 最新 HumanMessage                  [6-9] 最近几轮（保留）
                                        [10] 最新 HumanMessage
```

**关键设计**：
- **显式系统隔离 (Fencing)**：摘要块采用 `<memory-context>` 包裹，并硬编码前缀 `[System note: The following is recalled memory context...]`。这彻底阻断了模型将“过去的摘要”误认为“当前用户指令”的幻觉。
- **100% 缓存继承**：由于生成的 `<memory-context>` 被严格插入在受保护的头部（System Prompt + 首轮对话）**之后**，即使发生摘要重置，占据最多 Token 的头部信息依然完全静止，**完美命中 Prompt Cache**。
- **结构化输出保证 (with_structured_output)**：由于摘要作为上下文的关键基石，不可出现 JSON 损坏或格式错误。框架已废弃早期容易失败的正则表达式提取，全面采用 LLM 的 `with_structured_output(StructuredSummary)` 机制强制确保输出符合 12 字段结构，消除了因上下文内容干扰导致摘要结构错乱的问题。
- **服务端防并发控制 (Concurrent Compaction Lock)**：在多用户 / 多任务 Server 侧（`compact_chat`），同一 `chat_id` 的压缩操作由进程级 `asyncio.Lock` 保护。这防止了用户短时间内多次发起任务导致两个并行任务同时触发 `Summarize` 并写入相同的锚点，进而导致持久化内容被覆盖或历史上下文意外损坏。

### 4.6 工具保护机制

`ToolProtectionConfig`（`schemas.py`）定义哪些工具的输出不可被**过滤**：

```python
BUILTIN_PROTECTED_TOOLS = frozenset({"skill_select_tool", "todo_write"})
```

注意：保护只针对 Filter（不可逆），不针对 Compress（可逆）。压缩后 Agent 可以通过 `cat` 恢复原始内容。

---

## 5. Pipeline 架构与缓存协同

### 5.1 处理器执行顺序

`build_default_processors()`（`pipeline/engine.py`）定义统一的默认处理器链；
`create_default_pipeline()`、`context_pipeline_middleware.py` 和 Evolution pipeline
都复用这条链，避免不同入口出现不同的缓存行为：

```
ThinkingBlockCleaner     ← 首先清理 thinking blocks，减少无效 token
       ↓
MediaFilterProcessor     ← 文本模型主动剥离 image/video/audio（避免 400 + 省 token）
       ↓
FilterProcessor          ← 大型工具结果 → 磁盘持久化 + 智能预览 + 文件引用
       ↓
CacheTtlPruneProcessor   ← cache 过期时归档/裁剪旧工具结果（零 API 成本、结构化引用、预算化恢复）
       ↓
CompressProcessor        ← 旧工具调用 → 紧凑格式（批量清理）
       ↓
SessionNotesProcessor    ← 笔记就绪时零 API 压缩；未就绪时自然透传
       ↓
SummarizeProcessor       ← 超大上下文 → 结构化摘要（最后手段）
       ↓
NormalizeProcessor       ← 内容标准化（清理空行、换行符）
       ↓
ExplicitCacheProcessor   ← 注入 cache_control 断点（最后执行）
```

**ExplicitCacheProcessor 在最后执行的原因**：它需要在所有上下文操作完成后，基于最终的消息列表计算断点位置。如果先注入断点再压缩，断点位置会失效。

### 5.1.1 Cache-TTL 归档恢复闭环

`CacheTtlPruneProcessor` 不只依赖时间推断缓存过期。Pipeline middleware 会优先读取业务层显式注入的 `ProcessorContext.metadata["cache_usage_feedback"]`；没有显式值时，使用 `cache_metrics_collector` 从当前请求内真实 provider response usage 累计出的 `CacheUsageFeedback`。该对象包含 `cache_hit_rate`、`cached_tokens`、`input_tokens`、`calls`：

- 热缓存：存在 `cached_tokens` 且命中率达到热阈值时跳过 TTL 裁剪，保护仍然有效的前缀。
- 冷缓存：调用次数或输入 tokens 达到稳定样本后，低命中率会提前触发旧工具结果裁剪，避免等待固定 TTL。
- 安全阀：即使命中率判断为冷，仍必须满足上下文占比和可裁剪 token 门槛，避免为了很小收益破坏消息历史。

处理器执行时先在工作消息列表中生成替换后的 `ToolMessage`，再一次性提交到 `ProcessorContext.messages`。归档成功、soft trim 成功、offload 失败、预算延后分别进入 `TaskMetrics`。成功归档结果按 `chat_id`、工具名、`tool_call_id`、内容长度和 `content_sha256` 组成处理器内幂等键；运行时归档存储按会话、工具、原始内容哈希和原始字节数生成内容寻址路径，并在复用前校验 metadata、归档 payload 哈希和 schema-v2 restore-map sidecar。restore-map 由 runtime 层统一契约生成和读取，包含 `content_index`、推荐范围来源、路径归一化和行号边界校验；快速复用与写入复用都会自愈损坏、schema 不匹配或缺失的 restore-map sidecar。同一会话 retry 同一工具结果时保持 archive ref 和恢复路径稳定，且不会重复写入归档。无 `chat_id` 的匿名上下文不写入共享归档目录。失败结果不进入缓存，后续 retry 仍会重新尝试 offload。预算指标区分两类语义：`deferred_reasons` 只表示未修改消息的真实剪枝延期；归档写入预算不足进入 `archive_deferred_reasons`，若随后结构感知 soft trim 成功，则同时记录 `archive_deferred_soft_trimmed_reasons`；归档写入和归档复用分别进入 `archive_written_count`、`archive_reused_count`、`archive_bytes_written`、`archive_bytes_reused`。当会话内 pruning 净收益为负、refetch 比例达到配置阈值、typed restore 成本占比达到阈值，或 typed restore 后保留 ROI 低于阈值时，后续 pass 会提高裁剪阈值和最小可裁剪 token 门槛，避免同一会话在低收益归档/恢复之间震荡。接近硬上下文上限时，`emergency_prune_ratio` 会允许 cache-TTL 剪枝在 HITL / resume 状态下绕过热缓存保护执行，优先避免请求越过模型窗口。

归档写入回调返回 `ContextOffloadResult`，用 `temporary_failure`、`permission_denied`、`quota_exceeded`、`unsupported` 区分失败类型；失败类型以 `offload_failure_kinds` 进入 `CompressionEvent` 与 `TaskMetrics`。归档引用由 `ContextArchiveReference` 生成，除路径、哈希、原始 token/字符数外，还带轻量 `content_index` 和可直接传给文件读取工具的 `chunk_restore_args`：

- `line_count`、`chunk_size_lines`、`chunk_count` 用于判断是否需要分段恢复。
- `chunk_ranges` 只暴露行号范围，不复制原文。
- `chunk_restore_args` 暴露前 12 个分块的 `path:start-end` 参数；恢复阻断事件还会携带 `restore_range_hints`，用 `error_keyword`、`section_heading`、`code_block`、`table_range`、`list_range`、`fallback_chunk` 等原因标记推荐范围，鼓励 GUI 和模型按结构恢复而不是整文件回读。
- JSON 对象会通过 `content_features` 暴露受限数量的顶层 key 名，JSON 数组会暴露长度，帮助模型定向读取字段或分段扫描数组。
- Markdown 标题、代码块、表格和列表项只暴露结构类型、数量和行号范围，便于 GUI 和模型推荐最小恢复范围，不把正文重新塞回上下文。

恢复读取由文件工具执行层统一拦截 `.context/{session_id}/compacted/` 路径，并在暴露内容前校验会话归属、整文件恢复 token 上限、单路径读取次数和单任务恢复 token 上限。整文件读取先用文件大小估算触发预算硬闸；如果文件大小探测失败，执行层返回 `archive_restore_size_probe_failed` 阻断，不暴露归档正文。范围读取继续通过 `chunk_restore_args` 的 `path:start-end` 参数恢复；typed GUI/server restore 读取靠后的大行号范围时会在归档旁生成并复用稀疏 byte-offset 行索引，同一归档的晚段恢复从最近行锚点 seek，避免从文件开头线性扫描。预算失败时返回稳定的结构化 blocked payload，而不是自然语言错误；payload 包含 `type`、`reason`、`archive_path`、`estimated_tokens`、`message`、`suggested_action`，并扁平输出恢复指引字段 `reason_label_key`、`severity`、`primary_restore_arg`、`recommended_ranges`、`restore_range_hints`、`content_features`、`guidance_source`、`fallback_reason`。恢复指引优先读取 schema 合法且行号范围有效的 restore-map sidecar；schema v2 sidecar 必须携带 `content_index`，所有支持的 sidecar 都必须通过统一路径和行号校验；sidecar 缺失、不可读或无效时返回固定分段范围和明确 fallback reason。同时写入 `TaskMetrics.archive_restore_blocked_count` 和 `ArchiveRestoreBlockEvent`，GUI 和上层 Agent 可以据此提示用户缩小读取范围或继续使用摘要引用。聊天流中，`cache_ttl_prune` 会发出 `context_pruned` 状态步骤；成功 offload 后 `ArchiveSummaryService` 异步写入 EpisodicMemory checkpoint，并通过 `archive_checkpoint` 状态步骤和 operation ledger 通知 GUI。压缩前 `PreCompactProcessor` 会 scroll 最近 checkpoint milestone 注入 protected 尾部。工具拦截层会把 `archive_restore_blocked` payload 转发为结构化 `agent_status`，前端只消费结构化事件来展示 `archive_restore_blocked` 进度步骤和 toast。Session Analytics 的 `context_health.cache` 使用会话总量展示成本，但 retention observation 优先选取 dominant model 的 `modelBreakdown` 样本，并在无精确原始 key 时使用 provider 前缀归一后的唯一精确匹配；归一结果存在歧义时回退会话聚合，避免混合模型会话把主模型真实缓存命中稀释成聚合误判，也避免把不同 provider 的同名模型误合并。

归档范围恢复索引基准采用 200,000 行 UTF-8 文本，恢复第 199,500-199,700 行：无索引流式读取 142.45ms、峰值 25.2KiB；首次构建索引并读取 478.96ms、峰值 188.2KiB；复用索引读取 2.85ms、峰值 129.3KiB。索引复用路径用于频繁读取同一大归档的靠后行号范围，首次构建成本由同一归档的多次范围恢复摊销。

### 5.2 处理器间的缓存协同

**CompressProcessor → ExplicitCacheProcessor**：

压缩处理器在执行后记录压缩边界：

```python
context.metadata["last_compress_boundary_index"] = boundary_idx
context.metadata["compression_count"] = compression_count
```

显式缓存处理器读取压缩边界，在该位置设置保护性断点：

```python
compress_idx = context.metadata.get("last_compress_boundary_index")
if compress_idx is not None and compress_idx not in breakpoints:
    breakpoints.append(compress_idx)
```

**ThinkingBlockCleaner → 缓存效率**：

清理历史消息中的 `reasoning_content` / `thinking_blocks`，减少无效 token 占用。按模型和消息类型智能处理：
- Anthropic：保留 `thinking_blocks`，清理 `reasoning_content`
- DeepSeek/MiMo/Kimi 等 thinking 模型：选择性清理 `reasoning_content`——API 仅要求 tool_calls 消息保留 reasoning_content，纯文本回复的历史 reasoning_content 安全删除（与 Reasonix、OpenClaw 策略一致）
- 其他模型：清理 `thinking_blocks`，保留 `reasoning_content`

间接提升缓存效率——更少的 token 意味着更晚触发压缩，更少的缓存破坏。典型 DeepSeek 会话可节省数万 tokens。

### 5.3 中间件集成

`context_pipeline_middleware.py` 将 Pipeline 集成到 Agent 的中间件链中：

```python
context = ProcessorContext(
    messages=messages,
    llm=llm,
    metadata={
        "model_name": model_name,   # 用于 ExplicitCacheProcessor 判断是否需要处理
        "turn_count": turn_count,   # 用于 CompressProcessor 动态阈值
        "compression_intent": _extract_compression_intent(merged_ctx),  # 外部压缩焦点
    },
)
result = await current_pipeline.process(context)
```

Pipeline 按 `max_context_tokens` 缓存实例，避免重复创建。
`ContextPipeline.process()` 会在存在 `chat_id` 或当前任务上下文已设置 chat id 时持有 session-level context lock，确保同一会话的 Filter / CacheTtlPrune / Compress / Summarize 等消息变更串行提交；匿名上下文不创建全局默认锁，跨会话 pipeline 仍保持并行。`acquire_context_lock()` 对同一 asyncio 任务可重入，允许业务层已有锁保护时继续调用 pipeline 而不死锁。
压缩规划阶段额外遵循两条缓存友好约束：
- 只压缩完整的 `tool_call_id` 工具调用组，避免因压坏工具对而触发后续失败重试
- 不完整工具调用直接跳过，宁可少压一点，也不破坏 Prompt Cache 与消息结构稳定性
- `compression_intent` 只传递小体积结构化信号（如 `focus_files`、`focus_modules`、`failed_tool_call_ids`、`user_goal_hint`），避免把长文本业务语义注入稳定前缀而破坏缓存
- `failed_tool_call_ids` 已接入压缩优先级规划：失败工具调用即使输出内容看起来“像成功”，也会被提升为高优先级，减少错误恢复链路被过早压缩的概率
- `focus_files` / `focus_modules` 已接入压缩优先级规划：当前使用受控窗口扫描（头尾窗口）匹配工具调用参数、AI 调用内容与工具结果，在长输出里也能更稳地保护当前焦点
- `user_goal_hint` 已接入压缩优先级规划：当缺少明确文件/模块路径时，压缩器仍可根据稳定目标关键词延后压缩与当前任务强相关的工具调用组

### 5.5 Resume-Aware Cache Preservation（HITL专用）

**设计目标**：当Agent从`interrupt()`恢复时，保持历史messages完全不变，确保Prompt Cache命中率95%+。

**核心原则**（借鉴Manus最佳实践）：
1. **只追加，不删除**：Resume时绝对不修改历史messages
2. **HITL会话期间禁用Compress**：避免多次HITL交互时破坏cache
3. **配置一致性验证**：防止system_prompt/tools改变破坏cache前缀

**实现机制**：

**1. ProcessorContext增强**
```python
@dataclass
class ProcessorContext:
    # ...
    is_resume: bool = False  # Resume from interrupt()
    merged_context: dict[str, object] = field(default_factory=dict)  # 访问hitl_session_active
```

**2. BaseProcessor统一规则**
```python
def _should_skip_for_cache_preservation(self, context: ProcessorContext) -> bool:
    if context.is_resume:
        return True  # Resume时跳过
    if context.merged_context.get("hitl_session_active"):
        return True  # HITL会话期间跳过
    return False
```

**3. 修改性Processor行为**

| Processor | Normal | Resume | HITL会话期间 |
|-----------|--------|--------|-------------|
| MediaFilterProcessor | ✅ 剥离媒体 | ❌ 完全跳过 | ❌ 完全跳过 |
| FilterProcessor | ✅ 过滤 | ❌ 完全跳过 | ❌ 完全跳过 |
| CompressProcessor | ✅ 压缩 | ❌ 完全跳过 | ❌ 完全跳过 |
| SessionNotesProcessor | ✅ 更新 | ❌ 完全跳过 | ❌ 完全跳过 |
| SummarizeProcessor | ✅ 生成 | ❌ 完全跳过 | ❌ 完全跳过 |
| ExplicitCacheProcessor | ✅ 所有断点 | ✅ 仅最后一条 | ✅ 正常 |

**4. Resume流程**

```python
# base_agent.py
if isinstance(query, Command):  # Resume模式
    merged_context["is_resume"] = True

# context_pipeline_middleware.py
is_resume = merged_ctx.get("is_resume", False)
context = ProcessorContext(
    messages=messages,
    is_resume=is_resume,
    merged_context=merged_ctx,
)

# 上下文溢出检测
if is_resume and total_tokens > max_context_tokens:
    raise ValueError("Resume failed: context overflow")
```

**5. HITL Session管理（业务层）**

```python
# myrm-agent-server/app/api/agents/general_agent.py
if request.resume_value is not None:
    params.context["hitl_session_active"] = True  # 标记HITL会话活跃
```

**缓存效果**：

| 场景 | Before | After | 提升 |
|------|--------|-------|------|
| 单次HITL Resume | 0% | 95%+ | ♾️ |
| 多次HITL交互 | 0% | 90%+ | ♾️ |
| Resume成本 | $3.00/M | $0.30/M | 90% ↓ |
| Resume TTFT | 2000ms | 800ms | 60% ↓ |

**配套工具**：
- `infra/resume_validator.py`：配置一致性验证（agent_id, system_prompt, tools）
- 错误恢复清理：Resume失败时自动清理checkpoint（业务层实现）

---

## 6. LLM 层集成

### 6.1 cache_control 传递链路

```
ExplicitCacheProcessor                    LiteLLM / Anthropic SDK
  │                                         │
  ├─ msg.additional_kwargs["cache_control"]  │
  │  = {"type": "ephemeral", "ttl": "1h"}   │  ← Anthropic 直连/Vertex 时
  │  = {"type": "ephemeral"}                 │  ← 代理/未知端点时（默认 5min）
  │                                         │
  └─────────────────────────────────────────→ API 请求中携带 cache_control
```

`llm.py` 中的注释明确了设计决策：

```python
# 显式缓存（Claude/Qwen）完全由 Pipeline 的 ExplicitCacheProcessor 控制
# 不再使用 LiteLLM 的 cache_control_injection_points 配置
# 这样可以实现更智能的多断点策略
```

**为什么不用 LiteLLM 的内置缓存配置**：LiteLLM 的 `cache_control_injection_points` 只支持简单的固定位置注入（如 "last-user-message"），无法实现框架需要的多断点策略（System + 压缩边界 + 20-block 保护 + 最后消息）。

### 6.2 自动前缀缓存模型

OpenAI / DeepSeek / Gemini 使用自动前缀缓存，无需显式标记。框架对这些模型的优化是**隐式的**——通过工具分层排序、System Prompt 冻结、批量清理等策略保持前缀稳定，自动享受缓存折扣。

### 6.3 缓存效果可观测性

框架在三个层次追踪缓存命中情况：

#### 层次 1：断点设置预期（ExplicitCacheProcessor）

在设置断点时，计算预期可缓存的 tokens：

```python
expected_cacheable_tokens = estimate_messages_tokens(messages[: last_breakpoint + 1])
total_estimated_tokens = estimate_messages_tokens(messages)
expected_hit_rate = expected_cacheable_tokens / total_estimated_tokens

# 日志输出
📊 [ExplicitCache] 断点: [0, 15, 30, 45] | 预期可缓存: ~8500 (85.0%)
```

#### 层次 2：会话级缓存效果统计（token_tracker.py）

累积追踪整个会话的 token 使用量，并在会话结束时计算总体缓存效果：

```python
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0       # 缓存命中的 token 数
    reasoning_tokens: int = 0
    
    def get_cache_effectiveness(self) -> dict[str, float]:
        """计算会话级缓存效果"""
        cache_hit_rate = self.cached_tokens / self.prompt_tokens
        
        # 成本节省（相对于无缓存场景）
        original_cost = self.prompt_tokens * 1.0
        actual_cost = self.cached_tokens * cache_read_ratio + (self.prompt_tokens - self.cached_tokens) * 1.0
        cost_savings_pct = (original_cost - actual_cost) / original_cost
        
        return {
            "cache_hit_rate": cache_hit_rate,
            "cost_savings_pct": cost_savings_pct,
            "cost_savings_absolute": original_cost - actual_cost,
        }
```

在会话结束时（`base_agent.py`），自动输出累积统计：

```
💰 [Session Cache Summary] Calls: 12 | Hit Rate: 85.3% | Cost Savings: 81.0% (7738 tokens)
```

`_extract_cached_tokens()` 从 LiteLLM 统一格式中提取缓存数据，支持所有提供商：

| 提供商 | 原始字段 | LiteLLM 统一映射 |
|--------|---------|-----------------|
| OpenAI | `prompt_tokens_details.cached_tokens` | `prompt_tokens_details.cached_tokens` |
| Anthropic | `cache_read_input_tokens` | `prompt_tokens_details.cached_tokens` |
| Gemini | `cachedContentTokenCount` | `prompt_tokens_details.cached_tokens` |
| DeepSeek | `prompt_cache_hit_tokens` | `prompt_tokens_details.cached_tokens` |

#### 层次 3：单次调用命中率与成本节省（utils/logger.py）

每次 LLM 调用在详细日志路径下显示缓存命中率与相对「全部按普通 input 计价」的节省比例。数值由 ``utils/token_economics/cache_economics.compute_prompt_cache_stats(prompt_tokens, cached_tokens, cache_read_ratio=0.1)`` 计算；NDJSON 指标与 ``TokenUsage.get_cache_effectiveness()`` 使用同一函数。

语义要点：普通 input 计价系数 1.0，cache read 计价系数通过 ``cache_read_ratio`` 参数化（默认 0.1 匹配 Anthropic，OpenAI 为 0.5）；不纳入首次 cache write 的加价项（与 §6.3 下文说明一致）。

```python
stats = compute_prompt_cache_stats(prompt_tokens, cached_tokens)
cache_hit_rate = stats["cache_hit_rate"]
cost_savings_pct = stats["cost_savings_pct"]
```

日志输出示例：

```
📥 LLM API Response:
  Token Usage:
    - Prompt Tokens: 10000
    - Cached Tokens: 8530
    💾 Cache Hit Rate: 85.3% | Cost Savings: 81.0%
```

**成本节省公式说明**（相对于无缓存场景）：
- 无缓存成本 = 10000 × 100% = 10000 单位
- 有缓存成本 = 8530 × 5% + 1470 × 100% = 426.5 + 1470 = 1896.5 单位
- 节省 = (10000 - 1896.5) / 10000 = 81.0%

**注意**：此计算不包含首次创建缓存的 125% 成本（一次性支付）。实际长期使用中，创建成本会被后续多次命中摊平。

通过三层可观测性，开发者可以：
1. **设置时预期**：断点是否合理，预期命中率
2. **会话级累积**：整体缓存效果，总成本节省
3. **单次调用实际**：即时验证命中率和成本节省

**完整的监控流程**：
```
Turn 1: 
  📊 [ExplicitCache] Expected Cache: 0%    ← 首次无缓存
  📥 LLM Response: Cached: 0 tokens         ← 首次创建缓存

Turn 2:
  📊 [ExplicitCache] Expected Cache: 85%   ← 预期 85% 命中
  📥 LLM Response: Cached: 8530 tokens      ← 实际 85.3% 命中
  💾 Cache Hit Rate: 85.3% | Cost Savings: 81.0%

Turn 12 (会话结束):
  💰 [Session Cache Summary] Calls: 12 | Hit Rate: 85.3% | Cost Savings: 81.0% (7738 tokens)
                                                                          ← 会话总成本节省
```

#### 层次 4：可选 NDJSON 指标落盘（生产分析）

设置环境变量 ``MYRM_CACHE_METRICS_DIR`` 指向可写目录后，每次 ``log_llm_response`` 追加一行 JSON（NDJSON），按 UTC 日期写入 ``cache_metrics_YYYY-MM-DD.ndjson``。未设置该变量时不写盘、不进行文件 I/O。

**配对语义**：``context_pipeline_middleware`` 在每次模型调用开始时执行 ``clear_pending_explicit_cache_snapshot()``；``ExplicitCacheProcessor`` 在成功注入 ``cache_control`` 后执行 ``set_pending_explicit_cache_snapshot()``；``try_persist_cache_call_metrics`` 在记录本次响应时 ``take`` 并清空 pending，与**同一次** LLM 响应的 ``usage`` 合并写入。无显式缓存路径（未注入断点）时 ``explicit_cache_snapshot`` 为 ``false``，仍写入 ``usage`` 相关字段。

**记录字段（``schema_version`` = 1）**：

| 字段 | 含义 |
|------|------|
| ``recorded_at_utc`` | ISO8601 时间戳（UTC） |
| ``response_model`` | 响应中的模型名 |
| ``prompt_tokens`` / ``completion_tokens`` / ``cached_tokens`` | 来自 LiteLLM 标准化 ``usage``（仅支持 int/float/None，其他类型抛出 TypeError） |
| ``actual_cache_hit_rate`` | ``compute_prompt_cache_stats`` 返回的 ``cache_hit_rate``（``prompt_tokens <= 0`` 时为 0） |
| ``cost_savings_pct_vs_uncached_input`` | ``compute_prompt_cache_stats`` 返回的 ``cost_savings_pct``（与 §6.3 层次 3 一致） |
| ``explicit_cache_snapshot`` | 本次是否与显式缓存 pending 配对成功 |
| ``explicit_cache`` | 可选；仅含核心缓存指标：``turn_count``、``breakpoint_count``、``message_count``、``total_estimated_tokens``、``expected_cacheable_tokens``、``compression_count``（预期命中率可通过 ``expected_cacheable_tokens / total_estimated_tokens`` 实时计算） |

**部署与配置**：

- **单实例语义**：默认 ``threading.Lock`` 假定单框架实例。多实例部署（如水平扩展）时，**控制平面必须**为每个实例注入不同的 ``MYRM_CACHE_METRICS_DIR``（例如 ``/logs/metrics/instance-1``），或将数据路由到统一的日志聚合器，以避免多进程交错写入导致 NDJSON 格式损坏。并发写入经过严格测试：20线程高竞争场景下吞吐量>500写入/秒，``threading.Lock`` 确保原子追加，无数据损坏或记录丢失。
- **定价参数**：cache read 倍数通过 ``cache_read_ratio`` 参数化（默认 0.1 匹配 Anthropic 90% off，OpenAI 为 0.5 即 50% off），调用方按需传入。
- **异常检测**：``compute_prompt_cache_stats`` 自动钳制 ``hit_rate`` 到 [0, 1]。当 ``cached_tokens > prompt_tokens`` 时（``hit_rate > 1``），记录 WARNING 日志并钳制为 1.0，提示提供商 ``usage`` 异常。

**NDJSON记录示例**：

```json
{
  "schema_version": 1,
  "recorded_at_utc": "2026-03-20T12:00:00Z",
  "response_model": "claude-3-5-sonnet-20241022",
  "prompt_tokens": 10000,
  "completion_tokens": 50,
  "cached_tokens": 8530,
  "actual_cache_hit_rate": 0.853,
  "cost_savings_pct_vs_uncached_input": 0.81035,
  "explicit_cache_snapshot": true,
  "explicit_cache": {
    "turn_count": 2,
    "breakpoint_count": 4,
    "message_count": 10,
    "total_estimated_tokens": 10000,
    "expected_cacheable_tokens": 8500,
    "compression_count": 0
  }
}
```

记录大小：约496字节（实际大小取决于字段值长度）

**口径差异与解释**：

- **Expected vs Actual**：NDJSON 中预期命中率 ``expected_cacheable_tokens / total_estimated_tokens`` 为 ``ExplicitCacheProcessor`` 基于**静态消息序列**的预期值；``actual_cache_hit_rate`` 为提供商 ``usage`` 返回的真实命中率。
- **差异原因**：预期值假定无 KV-cache 漂移、无工具结果插入（严格前缀匹配）；实际值受消息对象变更、工具结果写入、系统压缩影响。持续高差异（实际远低于预期）提示架构漂移（参见 ``CONTEXT_ENGINEERING.md`` 的 Manus 指标警告）。

**字段设计原则**：

- **核心指标优先**：仅保留与缓存性能直接相关的指标（``turn_count``、``breakpoint_count``、``message_count``、token统计、命中率预估、压缩次数）
- **职责单一**：专注缓存性能指标，模型信息通过 ``response_model`` 获取，业务追踪（chat_id/user_id）通过日志聚合实现，配置常量（断点参数）属于文档而非数据

#### 层次 5：缓存断裂预防+诊断（Always-on）

**预防层**：``toolkits/mcp/schema_utils.canonicalize_schema_for_cache()`` 在 MCP 工具注册时对 ``inputSchema`` 做确定性 key 排序 + ``required``/``dependentRequired`` 集合排序，消除 MCP server 重连/重启后 schema 字段顺序抖动导致的前缀失配。

**诊断层**：``cache_break_detector.py`` 提供自动的缓存断裂检测和归因，独立于 NDJSON 持久化（always-on）。

**两阶段架构**：

1. **Pre-call**（``context_pipeline_middleware``）：``record_prompt_state()`` 计算 system prompt hash 和 model name，对比上一轮检测变化
2. **Post-call**（``try_persist_cache_call_metrics``）：``check_cache_break()`` 比较 ``cached_tokens`` 与上一轮值

**断裂判定**：``cached_tokens`` 下降 >5% 且绝对值 >2000 tokens。

**归因维度**：

| 维度 | 检测方式 |
|------|---------|
| ``system prompt changed`` | SHA-256 hash 对比 |
| ``model changed (A → B)`` | 模型名直接对比 |
| ``tools changed (+N/-N tools)`` | 工具列表 hash + 数量差异 |
| ``tool schema changed (tool_name)`` | 逐工具 hash diff |
| ``likely 5min/1h TTL expiry`` | 两次调用间隔推测 |
| ``likely server-side`` | 所有客户端指标不变，<5min 间隔 |

#### 技能目录与 Cache（更正 2026-05-25）

**易错点**：技能/MCP 目录**默认不在 SystemMessage**，而在 meta-tool 的 **tool description**：

| 内容 | 位置 | Cache 维度 |
|------|------|------------|
| Bound 技能 XML（含 MCP `mcp_*_skill`） | ``skill_select_tool.description``（``get_metadata_summary()``） | tool schema 前缀；列表稳定则 **不** 触发 ``tool_definitions_changed`` |
| todo_write 绑定说明 | ``todo_write`` tool description | 同上 |
| MCP 函数文档 | skill workspace ``/mcp/.../*.md``；经 ``skill_select_tool`` 返回 ToolMessage | 对话消息，非 system/tool schema |
| Active todo focus | ``progress_middleware`` **追加到最后一个 HumanMessage** | 不破坏 system prefix cache |
| Session Notes 摘要 | ``SessionNotesProcessor`` 注入 **HumanMessage** | 不破坏 cache |
| Summarize 摘要 | ``SummarizeProcessor`` 注入 **HumanMessage** | 不破坏 cache |
| 记忆上下文 | ``memory_context_middleware`` **SystemMessage** (one-shot) | 仅首轮 baseline 建立 |

``SkillMetadata.always=True`` 表示 **始终出现在 skill_select XML**（``always="true"`` 属性），**不是**写入 SystemMessage。

MCP 本身不直接改 SystemMessage；常见 ``system prompt changed`` 来自 planner / memory 等 middleware 的首轮 one-shot 注入，而非 MCP 协议或 skill_select 目录变更。

**压缩感知**：``CompressProcessor``、``CacheTtlPruneProcessor``、``SessionNotesProcessor``、``SummarizeProcessor`` 执行后均调用 ``notify_compaction()`` 重置基线，避免压缩后的正常缓存重建被误报为断裂。

**生命周期**：通过 ContextVar 管理（与 ``TokenTracker`` 同层次），``init_cache_break_detector()`` 在 ``base_agent.py`` 中与 ``init_token_tracker()`` 一起初始化。

**NDJSON 集成**：当 ``MYRM_CACHE_METRICS_DIR`` 启用时，断裂事件记录在 ``cache_break`` 字段中：

```json
{
  "cache_break": {
    "prev_cache_read": 10000,
    "curr_cache_read": 3000,
    "token_drop": 7000,
    "reasons": ["system prompt changed"],
    "cache_creation_tokens": 8000
  }
}
```

### 6.4 性能特性

框架缓存系统的性能开销经过严格基准测试验证，确保在生产环境中的影响可忽略不计。

**ExplicitCacheProcessor 开销**（排除日志输出）：

| 上下文规模 | 延迟范围 | 阈值 | 相对 LLM API 延迟 |
|-----------|---------|------|------------------|
| 小（10消息） | 1.8-3.9ms | <5ms | <0.5% (vs ~1s API) |
| 中（50消息） | 10-21ms | <25ms | <2.5% (vs ~1s API) |
| 大（150消息） | 37-45ms | <50ms | <5.0% (vs ~1s API) |

- **should_process 早退**：非 Anthropic 模型的过滤检查 <10μs（常量时间字符串匹配）
- **吞吐量**：30消息上下文处理吞吐量 100-266调用/秒（平均 ~150调用/秒）

性能范围基于多次运行实测数据（受系统负载影响）。所有阈值设置均包含缓冲以确保生产环境稳定性。

**NDJSON 并发写入性能**：

| 场景 | 吞吐量 | 数据完整性 |
|------|--------|-----------|
| 20线程高竞争 | >500写入/秒 | 100%（threading.Lock 原子追加） |
| ContextVar 线程隔离 | N/A | 100%（无跨线程泄漏） |

证据来源：``tests/unit/test_cache_processor_performance_benchmark.py``（5个基准测试）、``tests/unit/test_cache_metrics_concurrent.py``（5个并发测试）

---

## 7. 故障排查指南

### 7.1 缓存命中率为 0

**现象**：日志显示 `Cache Hit Rate: 0.0%`

**可能原因**：

1. **模型不支持 Prompt Cache**
   - 检查：模型是否为 Claude/Qwen 系列（需要显式 cache_control）或 OpenAI/Gemini/DeepSeek（支持自动前缀缓存）
   - 解决：
     - 对于 Claude/Qwen：检查日志中是否有 `📊 [ExplicitCache] Breakpoints` 消息，确认断点已注入
     - 对于 OpenAI 等：确认使用最新版本的 API（如 `gpt-4o-2024-08-06`），旧版本可能不支持

2. **首次调用（创建缓存）**
   - 说明：首次调用时缓存为空，只能创建缓存，无法命中
   - 正常：第二次调用开始才会有缓存命中
   - 验证：查看后续调用的 `cached_tokens` 是否增加

3. **消息序列变化（破坏前缀匹配）**
   - 原因：前缀缓存要求**严格的前缀匹配**，任何前序消息的变化都会导致缓存失效
   - 检查：对比两次调用的 `messages` 前缀是否完全一致（包括空格、标点、顺序）
   - 解决：确保前序消息不变，只追加新消息

4. **Token 数不足最小阈值**
   - 原因：Anthropic 要求每个断点至少 1024 tokens（Claude Sonnet/Opus 4.x）
   - 检查：日志中的 `Expected Cache: 0%` 提示未达到最小阈值
   - 解决：增加消息长度或等待对话累积足够 tokens

### 7.2 Expected vs Actual 差异大

**现象**：NDJSON 记录中计算的预期命中率（`expected_cacheable_tokens / total_estimated_tokens`）与 `actual_cache_hit_rate` 差异超过 20%

**可能原因**：

1. **架构漂移（动态内容注入）**
   - 原因：框架假定消息序列静态，但可能有动态内容注入（如时间戳、随机 ID）
   - 检查：对比实际发送的消息与预期消息是否一致
   - 解决：确保动态内容注入到 `user_message` 而非 `system_prompt` 或前序消息

2. **工具结果插入**
   - 原因：工具调用后插入工具结果消息，改变消息序列结构
   - 说明：这是正常行为，工具结果无法提前预测
   - 预期：差异通常 <10%，如果 >20% 则可能有问题

3. **压缩触发（批量清理）**
   - 原因：`CompressProcessor` 批量清理历史消息，减少 block 数量
   - 说明：压缩后会重置部分缓存（符合设计）
   - 验证：检查 `compression_count` 是否递增

4. **提供商 usage 异常**
   - 原因：`cached_tokens > prompt_tokens`（数据不一致）
   - 检查：NDJSON 中 `actual_cache_hit_rate > 1.0`（未钳制时）
   - 解决：联系提供商确认 API 返回的 `usage` 字段正确性

### 7.3 NDJSON 未生成

**现象**：设置了 `MYRM_CACHE_METRICS_DIR` 但未生成 NDJSON 文件

**可能原因**：

1. **环境变量配置错误**
   - 检查：确认环境变量名称拼写正确：`MYRM_CACHE_METRICS_DIR`
   - 验证：打印 `os.environ.get("MYRM_CACHE_METRICS_DIR")` 确认值已设置
   - 解决：确保在进程启动前设置（重启服务）

2. **目录权限不足**
   - 原因：指定的目录不可写
   - 检查：日志中是否有 `Failed to append cache metrics` 错误
   - 解决：确保目录存在且进程有写权限（`chmod 755`）

3. **LLM 调用失败**
   - 原因：`log_llm_response` 未被调用（LLM 调用失败或被拦截）
   - 检查：是否有 LLM 响应日志
   - 解决：确保 LLM 调用成功完成

4. **多实例写冲突**
   - 原因：多个实例写入同一目录，导致文件损坏
   - 检查：NDJSON 文件格式是否正确（每行独立 JSON）
   - 解决：为每个实例配置不同的 `MYRM_CACHE_METRICS_DIR`（如 `/logs/metrics/instance-1`）

### 7.4 缓存命中率突然下降

**现象**：原本 >80% 的命中率突然降到 <20%

**可能原因**：

1. **System Prompt 变化**
   - 原因：修改了 system prompt 或用户指令
   - 影响：破坏所有缓存前缀
   - 解决：避免频繁修改 system prompt；必要时通知用户缓存将重建

2. **模型切换**
   - 原因：切换到不同的模型（如 `claude-3-5-sonnet` → `claude-3-opus`）
   - 影响：不同模型的缓存不共享
   - 说明：这是正常行为

3. **会话重置**
   - 原因：新开会话或清空历史
   - 说明：新会话从零开始，首次调用无缓存命中

4. **提供商缓存 TTL 过期**
   - 原因：Anthropic 缓存 TTL 为 5 分钟（代理端点）或 1 小时（直连端点，框架已自动配置）
   - 影响：超过 TTL 未调用，缓存失效
   - 解决：直连端点已自动使用 1h TTL；代理端点高频调用场景下不影响，低频场景接受缓存重建

### 7.5 性能调优参数

**场景：高级用户需要调整断点策略**

当前参数（`ExplicitCacheProcessor` 构造函数）：
- `safe_block_interval=15`：每 15 blocks 设置保护性断点
- `min_message_gap=6`：断点间最小消息数（fallback 策略）
- `max_breakpoints=4`：最大断点数（Anthropic/阿里云限制）

**调优方向**：

1. **提高缓存粒度**
   - 调整：`safe_block_interval=10`（更小）
   - 效果：更多断点，更细粒度的缓存
   - 代价：更多 cache write 成本（首次创建）

2. **降低缓存粒度**
   - 调整：`safe_block_interval=19`（更大）
   - 效果：更少断点，更粗粒度的缓存
   - 代价：缓存命中率可能降低（超出 lookback window）

**约束分析**：
- 默认值 `15` 基于 Anthropic 官方 20-block lookback window（留 5-block 缓冲）
- 修改阈值会影响缓存命中率和写入频率（trade-off：写入成本 vs 节省收益）
- 低于 10：写入频繁，成本增加；高于 18：超出 lookback window，命中率下降

---

## 8. 代码索引

### 前缀稳定性

| 文件 | 职责 |
|------|------|
| `tool_management/tool_layers.py` | CORE/COMMON/EXTENDED 三层定义 + 工具注册表 |
| `tool_management/registry.py` | `resolve()` 按 layer + name 排序，确保工具定义顺序确定性 |
| `streaming/utils.py` | `get_datetime_prompt()` 生成时间标签 + `DATETIME_SYSTEM_RULES` 系统规则常量 |
| `streaming/model_discipline.py` | Per-model 执行纪律系统：`resolve_execution_discipline(llm)` 返回 3 层合并的固定文本（核心规则 + 工具强制 + per-model 纠正） |
| `streaming/message_builder.py` | `inject_datetime_tags()` 时间戳注入逻辑（当前消息 + 历史消息确定性注入） |
| `base_agent.py` | `_ensure_initialized()` 中追加 DATETIME_SYSTEM_RULES + resolve_execution_discipline(llm) + environment_prompt_line + canary 到 system_prompt |
| `app/ai_agents/agent_middlewares/user_instructions_middleware.py` | 用户指令注入到 System Prompt 之后（跨用户缓存感知） |
| `workspace_rules/middleware.py` | Workspace 规则注入（user_instructions 之后、memory_context 之前） |
| `middlewares/memory_context_middleware.py` | 记忆上下文注入位置的缓存感知设计 |
| `app/core/cron/adapters/agent_runner.py` | `_SILENT_SUFFIX` 条件性内容注入（确定性常量，缓存安全） |

### 显式缓存

| 文件 | 职责 |
|------|------|
| `pipeline/processors/cache_optimizer.py` | `ExplicitCacheProcessor` — 断点计算、Token 距离验证、cache_control 注入 |
| `infra/cache_metrics_collector.py` | 可选 NDJSON 指标（``MYRM_CACHE_METRICS_DIR``）、ContextVar 与 LLM 响应配对 |
| `utils/token_estimation.py` | `estimate_messages_tokens()` — Token 计算（支持图片、工具调用等） |
| `tests/agent/context_management/test_cache_optimizer_unit.py` | 单元测试 — 断点计算、Token 验证、边界条件、注入逻辑（15个核心测试用例） |
| `tests/agent/context_management/test_cache_integration.py` | 集成测试 — 完整缓存链路（Processor → NDJSON 配对、Expected vs Actual 差异检测）（6个集成测试） |
| `tests/agent/context_management/test_cache_metrics_collector.py` | 单元测试 — NDJSON 落盘、pending 配对、无环境变量时不写盘 |
| `tests/utils/test_prompt_cache_economics.py` | 单元测试 — ``coerce_usage_non_negative_int``（int/float/None）、``compute_prompt_cache_stats``（自动钳制+日志） |
| `tests/agent/context_management/test_cache_processor_performance_benchmark.py` | 性能基准测试 — ``ExplicitCacheProcessor`` 开销验证（小/中/大上下文、should_process早退、吞吐量）（5个基准测试） |
| `tests/agent/context_management/test_cache_metrics_concurrent.py` | 并发测试 — ``threading.Lock`` 正确性、ContextVar 线程隔离、高竞争写入吞吐量（5个并发测试） |

### 缓存友好的上下文缩减

| 文件 | 职责 |
|------|------|
| `pipeline/processors/cache_ttl_prune_processor.py` | `CacheTtlPruneProcessor` — cache TTL 过期或接近硬上下文上限时将旧工具结果归档为结构化引用或结构感知裁剪 |
| `pipeline/processors/cache_ttl_prune_helpers.py` | Cache TTL pruning helpers — 归档/裁剪 DTO、内容转换、占位符渲染和消息替换 |
| `infra/archive_reference.py` | `ContextArchiveReference` — 对归档工具结果提供稳定 DTO、内容哈希、会话归属、结构索引和模型可读恢复提示 |
| `infra/cache_policy.py` | `CacheTtlPrunePolicy` — 按模型/供应商解析官方 TTL 校准 profile，并允许业务层注入覆盖 |
| `tracking/task_metrics.py` | `TaskMetrics` — 记录真实剪枝延期、归档预算延期、归档写入/复用、归档恢复读取成本、净节省和执行层恢复读取预算 |
| `pipeline/processors/compress_processor.py` | `CompressProcessor` + `BatchCompactState` — 批量清理策略 |
| `strategies/compactor.py` | 可逆压缩实现（紧凑格式 + 外部化到文件，减 tokens 不减 blocks） |
| `strategies/summarizer.py` | 结构化摘要（缓存重置事件，减 tokens 且减 blocks） |
| `infra/context_budget.py` | `ContextBudget` — 动态阈值计算 |
| `schemas.py` | `ContextConfig` — 阈值定义、`COMPRESS_MIN_SAVE_DEFAULT`、`COMPACT_RULES` |

### Pipeline 与集成

| 文件 | 职责 |
|------|------|
| `pipeline/engine.py` | `ContextPipeline` — 处理器链执行引擎 |
| `pipeline/processors/media_filter.py` | 文本模型主动剥离 image/video/audio（避免 400） |
| `pipeline/processors/filter_processor.py` | 大型工具结果过滤（工具保护机制） |
| `pipeline/processors/summarize_processor.py` | 结构化摘要（最后手段） |
| `pipeline/processors/thinking_cleaner.py` | Thinking Block 清理（减少无效 token） |
| `middlewares/context_pipeline_middleware.py` | 中间件集成入口 |
| `toolkits/llms/llm.py` | LLM 层 cache_control 传递说明 |
| `utils/token_economics/cache_economics.py` | ``coerce_usage_non_negative_int``（严格类型检查）、``compute_prompt_cache_stats``（自动异常日志，``cache_read_ratio`` 参数化） — 日志、NDJSON、``get_cache_effectiveness`` 使用统一计数与定价逻辑 |
| `utils/token_economics/tracker.py` | ``TokenUsage.get_cache_effectiveness()`` — 调用 ``compute_prompt_cache_stats`` |
| `toolkits/llms/utils/logger.py` | 单次调用缓存日志（coerce + ``compute_prompt_cache_stats``）；``log_llm_response`` 内触发可选 NDJSON |
| `agent/base_agent.py` | 会话结束时输出累积缓存统计 |

### 设计文档

| 文件 | 内容 |
|------|------|
| `context_management/CONTEXT_ENGINEERING.md` | 业界理论（Manus、Anthropic、Factory Research） |
| `docs/architecture/datetime-injection.md` | 时间戳注入 & Prefix Cache 设计 |

---

## ⚠️ 动态内容注入警告：SystemMessage vs HumanMessage

> **严格遵守规则**：禁止将任何运行时动态生成的内容追加为 `SystemMessage`。

### 规则说明

**为什么？**
- 动态内容（如子 Agent 通知、Deep Research 结果、实时时间戳）每次不同
- `SystemMessage` 变化会破坏 Prompt Cache 前缀，导致所有后续缓存失效
- 这会导致 **10x 成本增加**（95% 缓存命中率 → 0%）

**正确做法**：
- 动态内容 **必须** 使用 `HumanMessage`
- 静态、确定性内容才能使用 `SystemMessage`

**错误示例**（严重性：P0）：
```python
# ❌ 错误：动态内容作为 SystemMessage
messages.append(SystemMessage(content=dynamic_notification))
```

**正确示例**：
```python
# ✅ 正确：动态内容作为 HumanMessage
messages.append(HumanMessage(content=dynamic_notification))
```

### 框架内已修复的位置

本框架已在以下位置修复了此问题：

1. **`base_agent.py:462`** — 子 Agent 通知注入
2. **`stream_executor.py:522`** — 子 Agent 完成通知注入
3. **`deep_research/orchestrator.py:774`** — Deep Research 结果注入
4. **`progress_middleware.py`** — Active todo focus 注入（HumanMessage via request.override）
5. **`security_guardrail_middleware.py`** — Circuit Breaker 环境约束注入（HumanMessage via awrap_model_call + request.override，瞬态不持久化）
6. **`budget_boundary_middleware.py`** — 预算警告/终止提示注入（HumanMessage with `[SYSTEM INSTRUCTION]` prefix）
7. **`citation_rules_middleware.py`**（server 层）— 引用规则注入（HumanMessage via request.override）

这些位置已添加代码注释，明确说明使用 `HumanMessage` 的原因。

### 开发者注意事项

**在添加新的动态内容注入时**：
1. 首先判断内容是否每次调用都可能变化
2. 如果是动态内容，**必须**使用 `HumanMessage`
3. 在代码中添加注释说明原因（参考上述三处修复）

**文档引用**：
- 详见 `CONTEXT_ENGINEERING.md` § Prompt Cache Best Practices
- 参考 Anthropic Claude API 官方指南：[Dynamic content in user messages](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching#dynamic-content-in-user-messages)
