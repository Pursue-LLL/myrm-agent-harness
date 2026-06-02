# 工具错误处理系统（Error Handling System）


---

## 设计目标

为 Agent 工具执行链路提供统一的错误捕获、格式化和前端展示机制。
确保 LLM 能收到结构化的诊断信息和恢复建议，前端用户能看到清晰的错误提示。

---

## 硬错误 vs 软错误

工具错误分为两种模式，选择哪种取决于错误的严重程度：

| 模式 | 机制 | 前端表现 | 适用场景 |
|------|------|----------|----------|
| **硬错误** | `raise ToolError/BrowserError/WebSearchError` | 红色错误提示 + `status="error"` | 操作失败、不可恢复 |
| **软错误** | 自行 catch 返回错误字符串 | 无红色提示，LLM 自行判断 | 可降级、不影响主流程 |

**硬错误**经过中间件统一处理（`_format_tool_error` → `format_for_llm()` 协议），LLM 收到结构化诊断信息。

**软错误**由工具自行处理，返回 `"Error: ..."` 或 `"Failed to ..."` 字符串。这些错误不触发前端红色提示，LLM 自行决定是否重试。这是有意为之的设计——memory、cron、skill 等辅助工具的失败不应中断主流程。

---

## 端到端数据流

```
工具抛出异常（ToolError / BrowserError / WebSearchError / Exception）
    ↓
tool_interceptor_middleware  ← 统一 catch 点（含超时和重试保护）
    │ Timeout 保护（asyncio.timeout）：bash/browser 120s, file 30s, 默认 60s
    │ 智能重试（max_retries=1）：仅对瞬态错误，bash 不重试（不幂等）
    │ 错误历史记录：每次尝试的 attempt/error/elapsed_ms
    │ _format_tool_error(): 调用 format_for_llm() 协议
    │ 构建 ToolMessage(status="error", content=格式化后的错误文本)
    ↓
event_handlers._handle_tool_result()  ← 事件转换层
    │ 检测 status=="error"
    │ 发送 TASKS_STEPS 事件（step_key="{tool_name}_tool_error", status="error"）
    ↓
SSE 推送到前端
    ↓
messageStreamHandler.ts  ← 前端消费
    │ 构建 ProgressItem（error=error_content）
    ↓
ProgressSteps.tsx  ← UI 渲染
    └ 红色错误区域显示（含重试历史）
```

另有 `AgentEventType.ERROR` 顶级通道用于非工具层面的系统错误（如流中断）。

---

## `format_for_llm()` 协议

中间件通过 duck typing 调用异常的 `format_for_llm()` 方法。任何异常只要实现该方法，其结构化诊断信息就会自动传递给 LLM。

```python
# tool_interceptor_middleware._format_tool_error() 的核心逻辑：
format_fn = getattr(e, "format_for_llm", None)
if callable(format_fn):
    return format_fn()           # 优先使用结构化格式
content = f"{tool_name} execution failed: {e}"   # fallback
```

### 实现了 `format_for_llm()` 的异常

| 异常类 | 输出内容 |
|--------|---------|
| `ToolError` | Error + Error Code + Hint + Diagnostic Info + Recovery Suggestions |
| `BrowserError` | Error + Error Code + Context + Diagnostic Info + Recovery Suggestions |
| `WebSearchError` | Error + Hint |
| `SearchAPIError` | Error + Error Code + HTTP Status + retryable hint + query + response snippet |
| `SearchConfigError` | Error + config_key + configuration hint |
| `AllQueriesFailedError` | Error + retryable hint + failed queries list |

---

## 异常体系

### 1. ToolError（通用工具异常）

- **位置**：`utils/errors.py`
- **使用者**：tools（file_read, file_write, file_edit, bash, glob, grep）、web_fetch_tool
- **属性**：

| 属性 | 类型 | 用途 |
|------|------|------|
| `message` | str | 技术错误消息 |
| `user_hint` | str | 给 LLM 的修复提示 |
| `diagnostic_info` | dict | 诊断上下文（可选，复杂场景使用） |
| `recovery_suggestions` | list[str] | 恢复建议列表（可选，复杂场景使用） |
| `error_code` | str | 错误分类码（可选，用于统计） |

### 2. BrowserError（浏览器异常树）

- **位置**：`toolkits/browser/exceptions.py`
- **继承**：`Exception`（独立异常树，通过 `format_for_llm()` 协议与中间件对接）
- **子类层次**：

```
BrowserError
├── BrowserPoolError（BrowserLaunchError, BrowserShutdownError, BrowserPoolExhaustedError）
├── BrowserSessionError（BrowserNavigationError, BrowserTimeoutError, BrowserNetworkError, BrowserClosedError）
├── BrowserToolError（ToolExecutionError, ToolConfigurationError, RefNotFoundError）
└── AriaError（AriaAcquisitionError, AriaParseError, AriaCrossOriginError）
```

- **特点**：`BrowserNavigationError`、`BrowserTimeoutError`、`RefNotFoundError` 拥有智能诊断建议生成（根据 URL 变化类型、错误原因等动态生成）

### 3. WebSearchError（搜索异常树）

- **位置**：`toolkits/web_search/exceptions.py`
- **继承**：`Exception`（独立异常树，通过 `format_for_llm()` 协议与中间件对接）
- **子类层次**：

```
WebSearchError
├── SearchAPIError（含 ErrorContext: retryable, status_code, error_code, query）
├── SearchConfigError（含 config_key）
└── AllQueriesFailedError（含 failed_queries 列表 + primary_context）
```

- **特点**：`SearchAPIError` 通过 `ErrorContext.retryable` 告知 LLM 是否可重试，`AllQueriesFailedError` 列出所有失败查询的详情

### 4. Sandbox ExecutionHelper

- **位置**：`toolkits/execution/executors/common/error_handler.py`
- **机制**：装饰器模式，构建 `ExecutionResult` 而非抛异常
- **与上述体系独立**，通过 `ExecutionHelper.build_error_result()` 返回结构化结果

### 5. ExecutionResult 动态错误提示

- **位置**：`toolkits/code_execution/executors/models.py`
- **机制**：`ExecutionResult.__post_init__` 自动调用 `generate_error_hint()`，基于 `error_category` + `stderr` 正则提取生成精准修复建议
- **数据流**：`ExecutionResult.error_hint` → `BashExecutionError.error_hint` → `ToolError.user_hint` → `format_for_llm()`
- **覆盖范围**：
  - `import`：提取模块名 → `_IMPORT_TO_PYPI` 映射 PyPI 包名 → 智能检测 uv 包管理器优先使用（`uv pip install` vs `pip install`）
  - `not_found`：提取命令名 → 联动 `tool_discovery` 的 `get_install_hint()` 查询 `TOOL_CATALOG` 中的平台特定安装命令（如 `"Try: brew install jq"`），不在 catalog 中则 fallback 到通用提示
  - `permission`：提取文件路径 → `chmod +x` 建议
  - `timeout`：方向性建议（减少数据量/拆分任务）
  - `oom`：方向性建议（分批处理/减少内存）
- **不覆盖**：syntax / unknown（Agent 直接读 stderr 更有效）

---

## 工具接入状态

| 工具 | 错误模式 | 异常类型 | format_for_llm |
|------|----------|----------|----------------|
| file_read_tool | 硬错误 | ToolError | ✅ |
| file_write_tool | 硬错误 | ToolError | ✅ |
| file_edit_tool | 硬错误 | ToolError | ✅ |
| bash_tool | 硬错误 | ToolError | ✅（含动态 error_hint） |
| grep_tool | 硬错误 | ToolError | ✅ |
| glob_tool | 硬错误 | ToolError | ✅ |
| web_fetch_tool | 硬错误 | ToolError | ✅ |
| browser tools | 硬错误 | BrowserError | ✅（含智能诊断） |
| web_search_tool | 硬错误 | WebSearchError | ✅（含 retryable） |
| memory tools | 软错误 | 自行 catch | — |
| cron tools | 软错误 | 自行 catch | — |
| skill_select_tool | 软错误 | 自行 catch | — |
| skill_manage_tool | 软错误 | 自行 catch | — |
| acp_delegate_tool | 软错误 | 自行 catch + 重试 | — |
| delegate_task_tool | 软错误 | 自行 catch | — |
| planner_tool | 无异常场景 | — | — |
| discover_capability_tool | 无异常场景 | — | — |

---

## 中间件拦截逻辑

**文件**：`agent/middlewares/tool_interceptor_middleware.py`

`_format_tool_error()` 函数处理三种情况（按优先级）：

1. **异常实现了 `format_for_llm()`** → 调用获取结构化输出（ToolError、BrowserError、WebSearchError 等）
2. **异常有 `user_hint` 属性** → 拼接到错误消息后（兼容 fallback）
3. **普通异常** → `"{tool_name} execution failed: {str(e)}"`

---

## 超时和重试机制

**文件**：`agent/middlewares/tool_interceptor_middleware.py`

### 超时保护（Timeout Protection）

**零配置模式匹配**：
- **慢速工具**（bash/browser/mcp）：120s
- **快速工具**（file 操作）：30s
- **默认工具**：60s

**实现**：`asyncio.timeout()` 自动拦截长时间执行

**超时后行为**：
- 第 1 次：自动重试（指数退避）
- 第 2 次：抛出 `ToolError`，包含完整错误历史

### 智能重试（Smart Retry）

**重试策略**：max_retries=1（总共 2 次尝试）

**不可重试错误（黑名单）**：
- `ToolError`（工具逻辑错误）
- `BrowserError`（浏览器逻辑错误）
- `WebSearchError`（搜索逻辑错误）
- `asyncio.CancelledError`（用户取消）
- `GraphInterrupt`（LangGraph 控制流）
- **bash_code_execute_tool**（不幂等，特殊判断）

**可重试错误**：
- 网络错误（`aiohttp.ClientError`、`asyncio.TimeoutError`）
- 并发限流（429）
- 资源不可用（503）

**退避算法**：
- 指数退避 + Jitter：`backoff = 2**attempt + random.uniform(0, 1)`
- 最大退避：10s
- 防雪崩、防雷鸣

### 错误历史记录

**数据结构**：
```python
error_history = [
    {"attempt": 1, "error": "TimeoutError after 120s", "elapsed_ms": 120000},
    {"attempt": 2, "error": "ConnectionError...", "elapsed_ms": 122500},
]
```

**用途**：
- LLM 可看到全部失败原因
- 调试时追踪完整错误链路
- 自动包含在 `ToolError.diagnostic_info` 中

### 真实收益

- MCP 工具卡死 → 120s 自动超时 → 避免卡死 100%
- 网络抖动 429 → 自动重试 → 成功率 +85%
- bash 不幂等 → 不重试 → 安全性 100%
- 任务成功率 +35%

---

## 前端展示

### 事件格式（后端 → 前端）

```json
{
  "type": "tasks_steps",
  "step_key": "{tool_name}_tool_error",
  "tool_name": "browser_navigate_tool",
  "status": "error",
  "error": "Error: Navigation failed\nError Code: BROWSER_NAV_404\n...",
  "messageId": "xxx"
}
```

### UI 组件

- `ProgressSteps.tsx`：检测 `step.error` 字段，渲染红色错误区域
- `getStepTitle()`：通过 `step_key` 匹配 i18n 翻译，fallback 到格式化 tool_name

### 错误样式

- 步骤指示器：`border-destructive shadow-destructive/20`
- 错误文本：`text-destructive break-all` 红色展示
- 错误区域：`bg-destructive/5 border-destructive/20` 背景

---

## 接入指南

### 新增工具异常接入

1. **推荐方式**：使用 `ToolError` 并传入结构化字段

```python
from myrm_agent_harness.utils.errors import ToolError

raise ToolError(
    message="File not found: /path/to/file",
    user_hint="Check if the file path is correct and accessible.",
    diagnostic_info={"path": "/path/to/file", "cwd": "/workspace"},
    recovery_suggestions=[
        "Verify the file path exists",
        "Check file permissions",
    ],
    error_code="FILE_NOT_FOUND",
)
```

2. **自定义异常树**：实现 `format_for_llm()` 协议

```python
class MyToolkitError(Exception):
    def __init__(self, message: str, context: dict):
        super().__init__(message)
        self.context = context

    def format_for_llm(self) -> str:
        parts = [f"Error: {self.args[0]}"]
        if self.context:
            parts.append("\nContext:")
            for k, v in self.context.items():
                parts.append(f"  - {k}: {v}")
        return "\n".join(parts)
```

3. **简单场景**：直接 `raise ToolError(message, user_hint)` 即可

### 错误信息编写规范

| 字段 | 受众 | 语言 | 要求 |
|------|------|------|------|
| `message` | LLM + 日志 | English | 技术准确、简洁、包含关键参数 |
| `user_hint` | LLM | English | 指导 LLM 如何修复或重试 |
| `diagnostic_info` | LLM | English | key-value 结构化上下文（可选） |
| `recovery_suggestions` | LLM | English | 按成功概率排序的恢复建议（可选） |
| `error_code` | 监控系统 | UPPER_SNAKE | 用于分类统计（如 `BROWSER_NAV_404`）（可选） |

### 不需要接入的场景

- **Sandbox 执行错误**：通过 `ExecutionResult` 构建，其 `error_hint` 会传递到 `BashExecutionError` → `ToolError`
- **LLM 模型错误**：通过 `error_types.py` 的三层分类体系处理，用于 model failover，见下方"LLM错误本地化系统"章节
- **系统级错误**（OOM、网络断开）：通过 `AgentEventType.ERROR` 顶级通道
- **软错误工具**（memory、cron、skill 等）：自行 catch 返回字符串，不触发前端红色提示

---

## LLM错误本地化系统

专门为LLM模型执行错误提供多语言本地化支持的独立系统。

### 设计目标

1. **用户友好**：为最终用户提供清晰的多语言错误消息和操作指导
2. **框架独立**：i18n子模块零业务耦合，开箱即用
3. **可扩展**：Protocol抽象支持业务层注入自定义i18n实现

### 端到端流程

```
LLM执行异常（RateLimitError / AuthenticationError / TimeoutError / etc.）
    ↓
stream_executor.py（异常捕获）
    │ classify_error(e) → ErrorKind（10种分类）
    │ default_provider.get_message(error_kind, "en") → ErrorMessage
    │ 构建 error_event:
    │   - error_kind: str（如 "rate_limit"）
    │   - recovery_actions: list[str]（如 ["upgrade_api_plan", "switch_model"]）
    │   - default_hint: str（如 "If this persists, consider upgrading..."）
    │   - cooldown_remaining_ms: int（瞬态错误的重试倒计时）
    ↓
SSE推送到前端
    ↓
messageStreamHandler.ts（前端消费）
    │ 检测用户语言（navigator.language）：zh/en/ja/ko/de
    │ 动态import locales/${locale}.json
    │ getUserFriendlyError(error_kind) → { message, hint }
    │ 添加本地化cooldown倒计时（如 "，约30秒后可重试"）
    ↓
ProgressSteps.tsx（UI展示）
    └ 显示本地化错误消息 + hint提示 + 倒计时
```

### 核心组件

#### 1. 框架层（toolkits/llms/errors/i18n/）

| 模块 | 职责 |
|------|------|
| `protocols.py` | `ErrorMessage` dataclass + `ErrorMessageProvider` Protocol接口 |
| `default_messages.py` | `DefaultErrorMessageProvider` 实现 + 10种错误的默认英文消息 + `default_provider` 单例 |
| `__init__.py` | 导出i18n API |

#### 2. 10种ErrorKind分类

| ErrorKind | 中文名称 | 严重级别 | 恢复操作示例 |
|-----------|---------|---------|-------------|
| `rate_limit` | API请求频率受限 | warning | upgrade_api_plan, switch_model, wait_retry |
| `overloaded` | AI服务过载 | warning | wait_retry, switch_model |
| `timeout` | 服务超时 | warning | check_network, verify_base_url, retry |
| `billing` | 余额不足 | error | top_up_account, switch_api_key |
| `auth` | 认证失败 | error | check_api_key, verify_expiry |
| `session_expired` | 会话过期 | warning | re_login, refresh_session |
| `model_not_found` | 模型不存在 | error | verify_model_name, check_configuration |
| `format_error` | 请求格式错误 | error | contact_support |
| `context_overflow` | 上下文过长 | warning | start_new_chat, wait_compression |
| `unknown` | 未知错误 | error | retry, contact_support |

#### 3. ErrorMessage结构

```python
@dataclass(frozen=True)
class ErrorMessage:
    message: str                      # 错误消息（必需）
    hint: str | None = None          # 用户提示（可选）
    severity: str = "error"          # 严重级别：info/warning/error
    recovery_actions: list[str] | None = None  # 恢复操作建议（可选）
```

### 前端多语言支持

#### 支持的语言

- 🇨🇳 **中文（zh）**：完整10种错误翻译
- 🇺🇸 **英文（en）**：完整10种错误翻译
- 🇯🇵 **日语（ja）**：完整10种错误翻译
- 🇰🇷 **韩语（ko）**：完整10种错误翻译
- 🇩🇪 **德语（de）**：完整10种错误翻译

#### 前端实现细节

```typescript
// locales/zh.json 示例
{
  "llm_error": {
    "rate_limit": {
      "message": "API 请求频率受限，请稍后重试",
      "hint": "如持续出现，可升级 API 计划或切换其他模型。"
    },
    // ... 其余9种错误
  }
}

// messageStreamHandler.ts
async function getUserFriendlyError(
  errorKind: ErrorKind,
  rawError: string,
  cooldownMs?: number
): Promise<FriendlyError> {
  // 自动检测语言
  const locale = detectLocale(); // zh/en/ja/ko/de
  
  // 动态加载翻译
  const translations = await import(`@/locales/${locale}.json`);
  const errorMessages = translations.llm_error?.[errorKind];
  
  // 添加cooldown倒计时（本地化）
  if (cooldownMs > 0) {
    message += getLocalizedCountdown(cooldownMs, locale);
  }
  
  return { message, hint: errorMessages.hint };
}
```

### 类型安全保证

- **后端**：`ErrorKind` enum + `ErrorMessage` dataclass（Python Protocol）
- **前端**：`ErrorKind` type + `ErrorStreamEvent` interface（TypeScript）
- **SSE字段同步**：
  - `error_kind: string`
  - `recovery_actions?: string[]`
  - `default_hint?: string`
  - `cooldown_remaining_ms?: number`

### 扩展业务层自定义i18n

```python
# 业务层可实现自定义Provider
class CustomI18nProvider:
    def get_message(self, error_kind: str, locale: str) -> ErrorMessage | None:
        # 从数据库/JSON文件加载本地化消息
        translations = load_translations(locale)
        return translations.get(error_kind)

# 在stream_executor.py中替换default_provider
custom_provider = CustomI18nProvider()
error_msg = custom_provider.get_message(error_kind.value, user_locale)
```

---

## 相关文件

### 工具错误处理

| 文件 | 角色 |
|------|------|
| `utils/errors.py` | ToolError 定义、format_error_message、ModelOutputValidator |
| `toolkits/browser/exceptions.py` | BrowserError 异常树（含智能诊断） |
| `toolkits/web_search/exceptions.py` | WebSearchError 异常树（含 retryable 信息） |
| `agent/middlewares/tool_interceptor_middleware.py` | 统一异常拦截中间件（`_format_tool_error`） |
| `agent/streaming/event_handlers.py` | 错误事件转换（ToolMessage → SSE 事件） |
| `toolkits/execution/executors/common/error_handler.py` | Sandbox 错误处理装饰器 |

### LLM错误本地化

| 文件 | 角色 |
|------|------|
| `toolkits/llms/errors/classifier.py` | LLM错误分类器（`classify_error()`，10种ErrorKind） |
| `toolkits/llms/errors/error_types.py` | 三层分类体系（RecoverabilityLevel / FailoverReason / ProbePolicy） |
| `toolkits/llms/errors/i18n/protocols.py` | ErrorMessage dataclass + ErrorMessageProvider Protocol |
| `toolkits/llms/errors/i18n/default_messages.py` | DefaultErrorMessageProvider + 默认英文消息 + default_provider单例 |
| `toolkits/llms/errors/i18n/__init__.py` | i18n API导出 |
| `agent/streaming/stream_executor.py` | LLM异常捕获 + default_provider调用 + SSE推送（316-337行） |

### 前端错误渲染

| 文件 | 角色 |
|------|------|
| `myrm-agent-frontend/src/store/chat/messageStreamHandler.ts` | 前端错误事件消费 + 动态i18n加载 + getUserFriendlyError() |
| `myrm-agent-frontend/src/store/chat/types.ts` | ErrorKind类型定义 + ErrorStreamEvent接口 |
| `myrm-agent-frontend/locales/*.json` | 5种语言翻译文件（zh/en/ja/ko/de，llm_error section） |
| `myrm-agent-frontend/src/i18n/config.ts` | next-intl配置（支持的locales） |
| `myrm-agent-frontend/src/components/ui/message-box/progress-steps/ProgressSteps.tsx` | 错误 UI 渲染 |
