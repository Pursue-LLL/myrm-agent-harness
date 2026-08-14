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
- infra.retention_helpers::build_tool_call_group_by_id, should_retain_tool_message, extract_* (POS: cross-processor retention contract)
- infra.tool_output_persister::persist_large_tool_output (POS: UECD evicted overflow persistence)
- strategies.filter::create_filtered_result, should_filter (POS: tool result filter)

[OUTPUT]
- FilterProcessor: oversized ToolMessage filter; retention path uses structure trim instead of LLM summary

[POS]
Pipeline filter stage. Persists large tool output to disk, then applies LLM summary or deterministic retain trim based on compression_intent signals.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ...infra.retention_helpers import (
    build_tool_call_group_by_id,
    extract_failed_tool_call_ids,
    extract_focus_files,
    extract_focus_modules,
    extract_user_goal_hint,
    format_retained_tool_trim_message,
    should_retain_tool_message,
    structure_trim_tokens_saved,
)
from ...infra.schemas import (
    DEFAULT_CACHE_TTL_PRUNE_CONFIG,
    DEFAULT_CONTEXT_CONFIG,
    TOOL_PROTECTION_CONFIG,
    ContextConfig,
    ToolProtectionConfig,
)
from ...infra.tool_output_persister import persist_large_tool_output
from ...infra.tool_result_trimming import trim_tool_result_content
from ...strategies.filter import (
    create_filtered_result,
    format_filtered_message,
    should_filter,
)
from ...strategies.tool_call_groups import ToolCallGroup
from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)


def _tool_call_group(
    group_by_tool_call_id: dict[str, ToolCallGroup],
    msg: ToolMessage,
) -> ToolCallGroup | None:
    tool_call_id = getattr(msg, "tool_call_id", None)
    if not isinstance(tool_call_id, str) or not tool_call_id:
        return None
    return group_by_tool_call_id.get(tool_call_id)


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
        for msg in context.messages:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else ""
                if should_filter(content, threshold=self.context_config.tool_result_evict_threshold):
                    return True
        return False

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
        retained_count = 0
        protected_tools: list[str] = []
        total_saved = 0
        failed_tool_call_ids = extract_failed_tool_call_ids(context.metadata)
        focus_files = extract_focus_files(context.metadata)
        focus_modules = extract_focus_modules(context.metadata)
        user_goal_hint = extract_user_goal_hint(context.metadata)
        group_by_tool_call_id = build_tool_call_group_by_id(context.messages)

        # 1. Single-tool filtering
        for msg in context.messages:
            if isinstance(msg, ToolMessage):
                if msg.name and self.protection_config.is_protected(msg.name):
                    protected_count += 1
                    protected_tools.append(msg.name)
                    logger.debug(f" [Filter] 跳过保护工具: {msg.name}")
                    continue

                content = msg.content if isinstance(msg.content, str) else ""
                if should_filter(content, threshold=self.context_config.tool_result_evict_threshold):
                    saved, retained = await self._filter_tool_message(
                        msg=msg,
                        content=content,
                        failed_tool_call_ids=failed_tool_call_ids,
                        focus_files=focus_files,
                        focus_modules=focus_modules,
                        user_goal_hint=user_goal_hint,
                        group=_tool_call_group(group_by_tool_call_id, msg),
                        filter_llm=filter_llm,
                        user_query=context.user_query,
                    )
                    if saved <= 0:
                        continue
                    total_saved += saved
                    if retained:
                        retained_count += 1
                    else:
                        filtered_count += 1

        if filtered_count > 0 or protected_count > 0 or retained_count > 0:
            log_parts = []
            if filtered_count > 0:
                log_parts.append(f"过滤 {filtered_count} 个，节省 ~{total_saved} tokens")
            if retained_count > 0:
                log_parts.append(f"保留 {retained_count} 个失败/错误工具输出(结构裁剪)")
            if protected_count > 0:
                log_parts.append(f"保护 {protected_count} 个关键工具")
            logger.warning(f" [Filter] {' | '.join(log_parts)}")

        context.tokens_saved += total_saved

        if protected_count > 0:
            context.operations.append(f"protected_tools:{','.join(set(protected_tools))}")

        return context

    async def _filter_tool_message(
        self,
        *,
        msg: ToolMessage,
        content: str,
        failed_tool_call_ids: frozenset[str],
        focus_files: frozenset[str],
        focus_modules: frozenset[str],
        user_goal_hint: str,
        group: ToolCallGroup | None,
        filter_llm: BaseChatModel | None,
        user_query: str,
    ) -> tuple[int, bool]:
        """Filter one tool message. Returns (tokens_saved, retained_error_path)."""
        saved_path = await persist_large_tool_output(content, msg.name)

        if should_retain_tool_message(
            msg,
            failed_tool_call_ids,
            focus_files=focus_files,
            focus_modules=focus_modules,
            user_goal_hint=user_goal_hint,
            group=group,
        ):
            trimmed = trim_tool_result_content(content, DEFAULT_CACHE_TTL_PRUNE_CONFIG)
            preview = trimmed.content if trimmed is not None else content
            msg.content = format_retained_tool_trim_message(preview, saved_path=saved_path)
            return structure_trim_tokens_saved(content, preview), True

        result = await create_filtered_result(
            content=content,
            file_path="",
            user_query=user_query,
            llm=filter_llm,
        )
        msg.content = format_filtered_message(result, saved_path=saved_path)
        return result.estimated_tokens, False
