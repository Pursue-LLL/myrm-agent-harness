"""Agent core runtime types.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- utils.token_tracker::TokenUsage (POS: Token 使用追踪类型，记录 prompt/completion/total tokens)
- agent.security.types::SecurityConfig (POS: 工具执行安全配置)
- streaming.types::ContextBudgetSnapshot (POS: 上下文预算快照)

[OUTPUT]
- CompletionStatus: LLM 回复完成状态枚举（COMPLETE, TRUNCATED, CONTENT_FILTERED）
- map_to_completion_status(): 将 LLM 提供商原始 finish_reason 映射为领域枚举
- AgentRunStatistics: Agent 执行统计数据类（duration, tool_call_count, token_usage, completion_status 等）
- QuoteAttachment: 划词引用附件（source_message_id, quoted_text），通过 HumanMessage.additional_kwargs 传递给 inject_ephemeral_quote()
- WorkspaceBinding: Agent 运行工作区绑定配置（mode, root_path, chat_id, task_id）
- AgentRuntimeSpec: Agent 运行时规范（agent_id, name, system_prompt, allowed_tools, skill_ids 等），Server 层编译、Harness 层执行
- AgentRuntimeConfig: Agent 运行时配置（recursion_limit, timeout_seconds, parallel_tool_calls, collect_artifacts, security_config）

[POS]
Agent core runtime type definitions. Defines completion status, run statistics, quote attachments, workspace bindings, and runtime specs.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.token_economics.tracker import TokenUsage

if TYPE_CHECKING:
    from myrm_agent_harness.agent.security.types import SecurityConfig
    from myrm_agent_harness.agent.streaming.types import ContextBudgetSnapshot
    from myrm_agent_harness.toolkits.mcp.config import MCPConfig


class CompletionStatus(StrEnum):
    """LLM response completion status — domain enum, provider-agnostic."""

    COMPLETE = "complete"
    TRUNCATED = "truncated"
    CONTENT_FILTERED = "filtered"


_TRUNCATED_REASONS = frozenset({"length", "max_tokens"})
_FILTERED_REASONS = frozenset(
    {
        "content_filter",
        "refusal",
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "RECITATION",
        "IMAGE_SAFETY",
    }
)


def map_to_completion_status(raw_finish_reason: str | None) -> CompletionStatus:
    """Map LLM provider's raw finish_reason to domain enum.

    OpenAI/DeepSeek/Moonshot: stop → COMPLETE, length → TRUNCATED, content_filter → CONTENT_FILTERED
    Anthropic:  end_turn → COMPLETE, max_tokens → TRUNCATED, refusal → CONTENT_FILTERED
    Gemini:     STOP → COMPLETE, MAX_TOKENS → TRUNCATED, SAFETY/BLOCKLIST/... → CONTENT_FILTERED
    """
    if raw_finish_reason in _TRUNCATED_REASONS:
        return CompletionStatus.TRUNCATED
    if raw_finish_reason in _FILTERED_REASONS:
        return CompletionStatus.CONTENT_FILTERED
    return CompletionStatus.COMPLETE


@dataclass
class AgentRunStatistics:
    """Agent execution statistics."""

    total_duration_seconds: float = 0.0
    node_execution_count: int = 0
    tool_call_count: int = 0
    message_chunk_count: int = 0
    was_cancelled: bool = False
    error_message: str | None = None
    token_usage: TokenUsage | None = None
    model_usage: dict[str, dict[str, object]] | None = None
    primary_model: str | None = None
    cost_usd: float = 0.0
    cost_status: str = "unknown"
    completion_status: CompletionStatus = CompletionStatus.COMPLETE
    compression_exhausted: bool = False
    context_budget: ContextBudgetSnapshot | None = None


@dataclass(frozen=True, slots=True)
class QuoteAttachment:
    """划词引用附件，用于在当前轮次瞬态注入引用文本。

    业务层（Server）接收前端划词引用请求时构建此对象，
    通过 HumanMessage.additional_kwargs 传递给 Harness 层。
    Harness 的 inject_ephemeral_quote() 将引用原文以 <quoted_context>
    XML 标签内联到当前 HumanMessage.content 中（阅后即焚）。
    DB 保存的是用户原始文本，下一轮从 DB 重建历史时引用自然消失，
    历史消息零修改，Prompt Cache 前缀 100% 命中。

    Attributes:
        source_message_id: 被引用的原始消息的数据库 ID。
        quoted_text: 用户划选的纯文本内容。
    """

    source_message_id: str
    quoted_text: str


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    """Workspace binding configuration for an agent run.

    Defines the root path and mode for the execution workspace, replacing the
    implicit reliance on session_id.
    """

    mode: str  # "chat", "background", or "subagent"
    root_path: str
    chat_id: str | None = None
    task_id: str | None = None
    inherit_parent: bool = False


@dataclass(frozen=True, slots=True)
class AgentRuntimeSpec:
    """The single source of truth for creating and running an agent.

    This specification encapsulates all runtime configuration, replacing fragmented
    parameters. It is compiled by the Server layer and executed by the Harness layer.
    """

    agent_id: str | None
    name: str
    system_prompt: str | None

    # --- Capabilities ---
    allowed_tools: list[str] = field(default_factory=list)
    tool_groups: list[str] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)
    skill_configs: dict[str, dict] | None = None
    mcp_servers: list[MCPConfig] = field(default_factory=list)
    openapi_services: list[dict[str, object]] = field(default_factory=list)

    # --- Runtime Policies ---
    memory_namespaces: list[str] = field(default_factory=list)
    workspace_binding: WorkspaceBinding | None = None
    max_iterations: int = 50
    unattended: bool = False

    # --- Additional Config ---
    locale: str | None = None
    channel_name: str | None = None
    security_config: SecurityConfig | None = None
    engine_params: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class EngineParams:
    """Tunable parameters for the agent execution engine (middlewares)."""

    max_tool_calls: int = field(default=30)
    max_bash_calls: int = field(default=15)
    max_replan_attempts: int = field(default=3)
    enable_replan: bool = field(default=True)
    enable_context_compression: bool = field(default=True)
    enable_parallel_tool_calls: bool | None = field(default=None)
    timeout_seconds: int | None = field(default=None)


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig:
    """Agent runtime configuration (distinct from config.llm.AgentConfig which is the full config bundle)."""

    recursion_limit: int = field(default=50)
    timeout_seconds: int | None = field(default=None)
    parallel_tool_calls: bool | None = field(default=None)
    collect_artifacts: bool = field(default=False)
    security_config: SecurityConfig | None = field(default=None)
    locale: str | None = field(default=None)
    channel_name: str | None = field(default=None)
    engine_params: EngineParams = field(default_factory=EngineParams)
    agent_id: str = field(default="")
