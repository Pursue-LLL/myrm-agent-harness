"""Adaptive Tool Result Content Router & Auto-Compactor Processor.

基于内容类型自适应嗅探 (JSON 数组, CSV/表格, Unified Diff, 重复日志, Grep 匹配)，
将工具结果精准路由到专用的无损紧凑化算子矩阵，实现多态内容自适应极致压缩。

[INPUT]
- pipeline.base::BaseProcessor, ProcessorContext
- pipeline.processors.content_router_types::AdaptiveCompactorConfig, AdaptiveCompactionResult, ToolResultFormatKind
- pipeline.processors.adaptive_tool_result_compactor::AdaptiveToolResultCompactor

[OUTPUT]
- AdaptiveToolResultRouterProcessor: 通用工具结果多模式无损压缩路由处理器
"""

from __future__ import annotations

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..base import BaseProcessor, ProcessorContext
from .adaptive_tool_result_compactor import AdaptiveToolResultCompactor
from .content_router_types import AdaptiveCompactionResult, AdaptiveCompactorConfig

logger = get_agent_logger(__name__)


class AdaptiveToolResultRouterProcessor(BaseProcessor):
    """基于内容类型自适应嗅探的通用工具结果多模式无损压缩流水线处理器."""

    def __init__(self, config: AdaptiveCompactorConfig | None = None) -> None:
        self.config = config or AdaptiveCompactorConfig()

    @property
    def name(self) -> str:
        return "adaptive_tool_result_router"

    async def should_process(self, context: ProcessorContext) -> bool:
        return bool(context.messages)

    def _process_text(self, text: str) -> tuple[str, AdaptiveCompactionResult]:
        res = AdaptiveToolResultCompactor.compact(text, config=self.config)
        if res.is_compacted:
            return res.compacted_text, res
        return text, res

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        compacted_count = 0
        total_saved_chars = 0
        by_format_counts: dict[str, int] = {}

        for msg in context.messages:
            if isinstance(msg.content, str):
                orig = msg.content
                compacted, res = self._process_text(orig)
                if res.is_compacted:
                    msg.content = compacted
                    compacted_count += 1
                    total_saved_chars += res.saved_chars
                    fmt_key = res.format_kind.value
                    by_format_counts[fmt_key] = by_format_counts.get(fmt_key, 0) + 1
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "text" and "text" in block:
                        orig_text = str(block["text"])
                        compacted_block, block_res = self._process_text(orig_text)
                        if block_res.is_compacted:
                            block["text"] = compacted_block
                            compacted_count += 1
                            total_saved_chars += block_res.saved_chars
                            fmt_key = block_res.format_kind.value
                            by_format_counts[fmt_key] = by_format_counts.get(fmt_key, 0) + 1

        if compacted_count > 0:
            existing_count = int(context.metadata.get("adaptive_compacted_count", 0))
            existing_saved = int(context.metadata.get("adaptive_compacted_saved_chars", 0))
            context.metadata["adaptive_compacted_count"] = existing_count + compacted_count
            context.metadata["adaptive_compacted_saved_chars"] = existing_saved + total_saved_chars
            logger.debug(
                " [AdaptiveToolResultRouter] 成功紧凑化 %d 处工具输出，节省 %d 字符，分布: %s",
                compacted_count,
                total_saved_chars,
                by_format_counts,
            )

        return context
