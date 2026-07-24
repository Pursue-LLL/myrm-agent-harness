"""过滤处理器

当单个工具结果超过阈值时：
1. 将完整输出持久化到工作区文件（crash-safe，保留完整内容）
2. 截断并生成智能预览（结构化内容提取 / LLM 摘要）
3. 在预览后附加文件路径引用，Agent 可通过 file_read_tool 按需读取

与 bash _output_eviction 的关系：
- _output_eviction 是第一道防线（即时，仅 bash 工具）
- FilterProcessor 是第二道防线（延迟，所有 ToolMessage）
- bash 输出经过 eviction 后已很小，不会触发 FilterProcessor
- all tools → FilterProcessor → tool_output_persister → UECD `.context/.../evicted/`

[INPUT]
- (none)

[OUTPUT]
- FilterProcessor: class — Filter Processor

[POS]
Provides FilterProcessor.
"""

from langchain_core.messages import ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.text_utils import get_token_count

from ...infra.schemas import (
    DEFAULT_CONTEXT_CONFIG,
    TOOL_PROTECTION_CONFIG,
    ContextConfig,
    ToolProtectionConfig,
)
from ...infra.tool_output_persister import persist_large_tool_output
from ...strategies.filter import (
    create_filtered_result,
    format_filtered_message,
    should_filter,
)
from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)


class FilterProcessor(BaseProcessor):
    """过滤处理器

    当单个工具结果超过阈值时：
    1. 持久化完整输出到磁盘（atomic_write, crash-safe）
    2. 生成内容描述（结构化数据用代码提取，非结构化用 LLM）
    3. 替换消息内容为截断预览 + 文件路径引用

    支持工具保护：某些关键工具的输出不会被过滤。
    """

    def __init__(
        self,
        protection_config: ToolProtectionConfig | None = None,
        context_config: ContextConfig | None = None,
    ):
        self.protection_config = protection_config or TOOL_PROTECTION_CONFIG
        self.context_config = context_config or DEFAULT_CONTEXT_CONFIG

    @property
    def name(self) -> str:
        return "filter"

    async def should_process(self, context: ProcessorContext) -> bool:
        # Check single-tool limit
        for msg in context.messages:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else ""
                if should_filter(
                    content, threshold=self.context_config.tool_result_evict_threshold
                ):
                    return True

        # Check aggregate limit for the latest turn
        latest_turn_msgs = self._get_latest_turn_tool_messages(context.messages)
        aggregate_tokens = sum(
            get_token_count(msg.content if isinstance(msg.content, str) else "")
            for msg in latest_turn_msgs
        )
        return aggregate_tokens > self.context_config.turn_aggregate_evict_threshold

    def _get_latest_turn_tool_messages(self, messages: list) -> list[ToolMessage]:
        """Get the contiguous block of ToolMessages at the end of the history."""
        turn_msgs = []
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                turn_msgs.append(msg)
            else:
                break
        return turn_msgs[::-1]

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        # Prompt Cache preservation: Skip filter during Resume or HITL session
        if self._should_skip_for_cache_preservation(context):
            logger.info(
                " [Filter] Skipped for Prompt Cache preservation (is_resume=%s, hitl_session_active=%s)",
                context.is_resume,
                context.merged_context.get("hitl_session_active"),
            )
            return context

        filter_llm = context.summarizer_llm or context.llm
        if filter_llm is None:
            logger.warning(" [Filter] LLM unavailable, structural filtering only")

        filtered_count = 0
        protected_count = 0
        protected_tools: list[str] = []
        total_saved = 0

        # 1. Single-tool filtering
        for msg in context.messages:
            if isinstance(msg, ToolMessage):
                if msg.name and self.protection_config.is_protected(msg.name):
                    protected_count += 1
                    protected_tools.append(msg.name)
                    logger.debug(f" [Filter] 跳过保护工具: {msg.name}")
                    continue

                content = msg.content if isinstance(msg.content, str) else ""
                if should_filter(
                    content, threshold=self.context_config.tool_result_evict_threshold
                ):
                    saved_path = await persist_large_tool_output(content, msg.name)

                    result = await create_filtered_result(
                        content=content,
                        file_path="",
                        user_query=context.user_query,
                        llm=filter_llm,
                    )

                    msg.content = format_filtered_message(result, saved_path=saved_path)
                    filtered_count += 1
                    total_saved += result.estimated_tokens

        # 2. Turn-level aggregate filtering
        latest_turn_msgs = self._get_latest_turn_tool_messages(context.messages)

        # Filter out protected messages from aggregate consideration
        unprotected_turn_msgs = [
            m
            for m in latest_turn_msgs
            if not (m.name and self.protection_config.is_protected(m.name))
        ]

        # Calculate current aggregate tokens
        def _get_tokens(m: ToolMessage) -> int:
            return get_token_count(m.content if isinstance(m.content, str) else "")

        aggregate_tokens = sum(_get_tokens(m) for m in unprotected_turn_msgs)

        if aggregate_tokens > self.context_config.turn_aggregate_evict_threshold:
            # Sort messages by size descending
            unprotected_turn_msgs.sort(key=_get_tokens, reverse=True)

            for msg in unprotected_turn_msgs:
                if (
                    aggregate_tokens
                    <= self.context_config.turn_aggregate_evict_threshold
                ):
                    break

                content = msg.content if isinstance(msg.content, str) else ""
                # Skip if already filtered by single-tool limit
                if "LARGE OUTPUT TRUNCATED" in content:
                    continue

                msg_tokens = _get_tokens(msg)

                saved_path = await persist_large_tool_output(content, msg.name)
                result = await create_filtered_result(
                    content=content,
                    file_path="",
                    user_query=context.user_query,
                    llm=filter_llm,
                )

                msg.content = format_filtered_message(result, saved_path=saved_path)
                filtered_count += 1
                total_saved += result.estimated_tokens

                # Update aggregate tokens (subtract original, add preview size)
                aggregate_tokens = (
                    aggregate_tokens - msg_tokens + result.estimated_tokens
                )

        if filtered_count > 0 or protected_count > 0:
            log_parts = []
            if filtered_count > 0:
                log_parts.append(
                    f"过滤 {filtered_count} 个，节省 ~{total_saved} tokens"
                )
            if protected_count > 0:
                log_parts.append(f"保护 {protected_count} 个关键工具")
            logger.warning(f" [Filter] {' | '.join(log_parts)}")

        context.tokens_saved += total_saved

        if protected_count > 0:
            context.operations.append(
                f"protected_tools:{','.join(set(protected_tools))}"
            )

        return context
