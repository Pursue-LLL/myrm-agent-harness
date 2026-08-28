"""cron_manage_tool LLM-visible description (prompt/cache SSOT).

Kept separate from ``cron_agent_tools.py`` so static tests and prompt audits can import
without pulling scheduling engine dependencies.

English and Chinese variants are both first-class LLM-facing strings.
Default locale is English; callers pass BCP-47 locale strings (e.g. ``zh-CN``).

[INPUT]
- utils.locale::is_chinese (POS: BCP-47 Chinese detection for description locale)

[OUTPUT]
- resolve_cron_tool_description: Locale-aware description resolver
- CRON_MANAGE_TOOL_DESCRIPTION_EN / _ZH: locale-specific SSOT constants

[POS]
Prompt SSOT for cron_manage_tool. Imported by cron_agent_tools.py and static tests.
"""

from __future__ import annotations

from myrm_agent_harness.utils.locale import is_chinese

DEFAULT_CRON_TOOL_DESCRIPTION_LOCALE = "en"

CRON_MANAGE_TOOL_DESCRIPTION_EN = """Manage scheduled tasks, recurring automations, and one-time reminders (create, list, update, delete, trigger, pause, resume, and browse templates).

## Common Usage Patterns (Choose ONE for action='add'):
1. Agent Task (Natural Language): prompt + ONE schedule param (cron_expr / every_minutes / at).
   - Recurring schedules (cron_expr / every_minutes) REQUIRE recurring_confirmed=true.
2. Shell Command Task: command + ONE schedule param. (Mutually exclusive with prompt).
3. Plain Reminder (No LLM): reminder=true + prompt + at (e.g. at="2026-03-01T10:00:00").
4. Blueprint Automation: blueprint + blueprint_values. (Pre-tuned prompt & schedule template).
5. Event/Stream Task (Real-time Trigger): stream_url (or poll_url) + (prompt OR command) + optional schedule.

## Actions:
- add: Create a task. Fill (prompt OR command OR blueprint) + ONE schedule parameter.
- list: Show all tasks. Use name_filter for fuzzy search (e.g. name_filter="backup").
- update: Modify an existing task. Requires job_id.
- remove: Permanently delete a task. Requires job_id.
- run: Trigger immediate execution of a task. Requires job_id.
- pause: Suspend task execution without deleting history. Requires job_id.
- resume: Resume a paused task. Requires job_id.
- blueprints: List available pre-tuned automation templates on demand.

## Schedule Parameters (For add/update — provide exactly ONE):
- cron_expr: Cron expression string, e.g. "0 9 * * *" (daily 9am), "*/30 * * * *" (every 30m), "0 9 * * 1-5" (weekdays).
- every_minutes: Recurring interval in minutes (integer, minimum 5).
- at: ISO 8601 datetime for one-time execution, e.g. "2026-03-01T10:00:00".

## Parameters:
- action: Operation to perform ('add', 'list', 'update', 'remove', 'run', 'pause', 'resume', 'blueprints').
- prompt: Instruction for the agent to execute when the task fires. Mutually exclusive with command.
- command: Shell command to execute when the task fires. Mutually exclusive with prompt.
- reminder: Set true for zero-LLM notification reminders (uses prompt as notification text, command not allowed).
- recurring_confirmed: Must be true when using cron_expr or every_minutes to confirm recurring execution.
- job_id: Target task ID (required for update, remove, run, pause, resume).
- name: Optional descriptive task name (auto-generated if omitted).
- name_filter: Fuzzy filter keyword for list action.
- model: Optional model identifier (e.g. "openai/gpt-4o-mini"). Leave empty to use default model.
- tz: IANA timezone for cron_expr, e.g. "Asia/Shanghai", "America/New_York".
- active_start: Start of daily active window in HH:MM (e.g. "09:00"). Task only fires within window.
- active_end: End of daily active window in HH:MM (e.g. "18:00").
- active_tz: IANA timezone for active hours window (defaults to UTC).
- max_fires: Maximum execution count before auto-stopping (0 = unlimited).
- expires_after: Auto-expiration duration ("3d", "2w", "3m") or ISO 8601 datetime ("2026-06-01T00:00:00").
- context_from: Comma-separated job IDs to inject latest output from into prompt (e.g. "job1,job2").
- blueprint: Blueprint template ID for template-based creation (use action='blueprints' to inspect options).
- blueprint_values: JSON object string of slot values for blueprint, e.g. '{"time": "08:00"}'.
- monitor_enabled: Set true to notify only when execution output changes compared to previous run.
- monitor_type: Change detection algorithm: "set" (line-delimited item diff) or "hash". Use "off" to disable.
- session_mode: Context sharing strategy: "isolated" (fresh context each run), "main" (chat session memory), "daily" (shares context within same calendar day).
- stream_url: WebSocket ("wss://...") or SSE URL for real-time trigger. Requires schedule as fallback.
- stream_protocol: Stream protocol ("ws" or "sse", defaults to "ws").
- stream_filter_json_path: JSONPath expression to extract field from stream events (e.g. "$.data.price").
- stream_filter_regex: Regex pattern to match extracted stream value.
- stream_headers: JSON object string of HTTP headers for stream connection.
- poll_url: HTTP URL to periodically fetch for change detection.
- poll_json_path: JSONPath to extract value from polling response.
- poll_interval_seconds: Polling interval in seconds (minimum 60, default 300).
- webhook_url: Optional webhook URL to deliver execution results (e.g. Slack/Feishu webhook).
- failure_webhook_url: Optional webhook URL dedicated for failure alerting.
- required_capabilities: Comma-separated required capabilities (e.g. "web_search_tool,net_fetch").
- tools_allowed: Comma-separated tool IDs allowed during task execution (e.g. "web_search,memory").""".strip()

CRON_MANAGE_TOOL_DESCRIPTION_ZH = """管理定时任务、周期性自动化与一次性提醒（支持创建、查询、修改、删除、即时触发、暂停、恢复与模板检索）。

## 常用调用模式（action='add' 时选择其一）：
1. Agent 任务（自然语言指令）：prompt + 任意一种调度参数（cron_expr / every_minutes / at）。
   - 周期性调度（cron_expr / every_minutes）必须显式传入 recurring_confirmed=true。
2. Shell 命令任务：command + 调度参数（与 prompt 互斥）。
3. 纯提醒事项（无需 LLM）：reminder=true + prompt + at（如 at="2026-03-01T10:00:00"）。
4. 蓝图自动化模板：blueprint + blueprint_values（自动填充调优后的提示词与调度规则）。
5. 实时流/轮询事件任务（触发式自动化）：stream_url（或 poll_url）+（prompt 或 command）+ 可选兜底调度。

## 操作指令（Actions）：
- add：创建新任务。需提供（prompt 或 command 或 blueprint）+ 恰好一个调度参数。
- list：列出所有任务。支持使用 name_filter 进行名称模糊搜索（如 name_filter="备份"）。
- update：修改任务配置。必须提供 job_id。
- remove：彻底删除任务。必须提供 job_id。
- run：立即手动触发执行一次任务。必须提供 job_id。
- pause：暂停任务调度（保留历史记录）。必须提供 job_id。
- resume：恢复处于暂停状态的任务。必须提供 job_id。
- blueprints：按需检索系统内置的自动化蓝图模板列表。

## 调度参数（add/update 时提供且仅提供一项）：
- cron_expr：标准 Cron 表达式，如 "0 9 * * *"（每天上午9点）、"*/30 * * * *"（每30分钟）、"0 9 * * 1-5"（工作日）。
- every_minutes：固定间隔执行分钟数（整数，最小值为 5）。
- at：一次性执行的 ISO 8601 时间字符串，如 "2026-03-01T10:00:00"。

## 参数说明：
- action：执行的操作指令（'add', 'list', 'update', 'remove', 'run', 'pause', 'resume', 'blueprints'）。
- prompt：任务触发时 Agent 执行的具体自然语言指令。与 command 互斥。
- command：任务触发时在沙箱中执行的 Shell 命令行。与 prompt 互斥。
- reminder：设置为 true 时创建免 LLM 的纯文本通知提醒（仅使用 prompt，禁止传 command）。
- recurring_confirmed：使用 cron_expr 或 every_minutes 创建周期性任务时必须显式设为 true。
- job_id：目标任务 ID（update, remove, run, pause, resume 操作时必填）。
- name：可选的任务名称（省略时将根据 prompt/command 自动生成）。
- name_filter：list 查询时的模糊过滤关键词。
- model：可选的模型名称（如 "openai/gpt-4o-mini"）。留空则使用默认模型。
- tz：Cron 表达式生效的 IANA 时区（如 "Asia/Shanghai", "America/New_York"）。
- active_start：每日允许运行的起始时间 HH:MM（如 "09:00"）。
- active_end：每日允许运行的截止时间 HH:MM（如 "18:00"）。
- active_tz：运行时间窗口的时区（默认 UTC）。
- max_fires：任务最大执行次数，达到后自动停止（0 表示无限制）。
- expires_after：任务自动过期时间段（"3d", "2w", "3m"）或具体日期（"2026-06-01T00:00:00"）。
- context_from：依赖的前置任务 ID（逗号分隔），将其最新执行结果自动注入到本任务 prompt 中。
- blueprint：蓝图模板 ID（可通过 action='blueprints' 查看可用模板）。
- blueprint_values：填入蓝图插槽的 JSON 对象字符串，如 '{"time": "08:00"}'。
- monitor_enabled：设为 true 时启用增量监控，仅当输出内容发生变化时才发送通知。
- monitor_type：增量检测算法："set"（按行比对新增项）或 "hash"（哈希比对）。"off" 表示关闭。
- session_mode：上下文复用模式："isolated"（每次全新隔离）、"main"（复用主对话历史）、"daily"（当天多次执行共享上下文）。
- stream_url：实时流事件监听地址（WebSocket 或 SSE）。须同时提供 schedule 作为兜底时机。
- stream_protocol：流协议类型（"ws" 或 "sse"，默认 "ws"）。
- stream_filter_json_path：从流消息中提取字段的 JSONPath 表达式（如 "$.data.price"）。
- stream_filter_regex：匹配提取值的正则表达式，仅命中时触发任务。
- stream_headers：流连接自定义 HTTP 请求头的 JSON 对象字符串。
- poll_url：定时轮询拉取变更的 HTTP URL。
- poll_json_path：轮询响应字段提取 JSONPath。
- poll_interval_seconds：轮询间隔秒数（最小 60 秒，默认 300 秒）。
- webhook_url：结果接收的 Webhook 地址（如飞书/钉钉/Slack 机器人）。
- failure_webhook_url：仅接收失败告警的专用 Webhook 地址。
- required_capabilities：任务执行所需的系统能力（逗号分隔，如 "web_search_tool,net_fetch"）。
- tools_allowed：任务执行期间挂载的工具列表（逗号分隔，如 "web_search,memory"）。""".strip()

CRON_MANAGE_TOOL_DESCRIPTION = CRON_MANAGE_TOOL_DESCRIPTION_EN


def resolve_cron_tool_description(
    locale: str | None = DEFAULT_CRON_TOOL_DESCRIPTION_LOCALE,
) -> str:
    """Return locale-aware LLM tool description for cron_manage_tool."""
    if is_chinese(locale):
        return CRON_MANAGE_TOOL_DESCRIPTION_ZH
    return CRON_MANAGE_TOOL_DESCRIPTION_EN


__all__ = [
    "CRON_MANAGE_TOOL_DESCRIPTION",
    "CRON_MANAGE_TOOL_DESCRIPTION_EN",
    "CRON_MANAGE_TOOL_DESCRIPTION_ZH",
    "DEFAULT_CRON_TOOL_DESCRIPTION_LOCALE",
    "resolve_cron_tool_description",
]
