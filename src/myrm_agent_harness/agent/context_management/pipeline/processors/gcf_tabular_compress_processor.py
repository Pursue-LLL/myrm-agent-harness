"""GCF 表格列式无损压缩处理器.

扫描消息列表中的 JSON 数组、Markdown 表格及 CSV 输出，
使用 GCF (Grid-Column Format) 列式重构消除重复键名并拍平嵌套路径。
提供 30%~48% 稳定无损 Token 压缩，并在异构度超过阈值或收益过低时自适应旁路熔断。

[INPUT]
- pipeline.base::BaseProcessor, ProcessorContext
- pipeline.processors.gcf_tabular_codec::GcfTabularCodec
- pipeline.processors.gcf_tabular_types::GcfCompressionGuardConfig, GcfCompressionResult

[OUTPUT]
- GcfTabularCompressProcessor: 表格列式无损压缩流水线处理器
"""

from __future__ import annotations

import json
from typing import cast

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..base import BaseProcessor, ProcessorContext
from .gcf_tabular_codec import GcfTabularCodec
from .gcf_tabular_types import GcfCompressionGuardConfig, GcfCompressionResult

logger = get_agent_logger(__name__)


class GcfTabularCompressProcessor(BaseProcessor):
    """GCF 表格列式无损压缩处理器."""

    def __init__(self, config: GcfCompressionGuardConfig | None = None) -> None:
        self.config = config or GcfCompressionGuardConfig()

    @property
    def name(self) -> str:
        return "gcf_tabular_compress"

    async def should_process(self, context: ProcessorContext) -> bool:
        return bool(context.messages)

    def _compress_string_content(self, text: str) -> tuple[str, GcfCompressionResult | None]:
        stripped = text.strip()
        # 1. 尝试 JSON 数组识别
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list) and all(isinstance(x, dict) for x in parsed):
                    dict_list = cast(list[dict[str, object]], parsed)
                    res = GcfTabularCodec.encode_object_array(dict_list, config=self.config)
                    if res.is_compressed:
                        return res.compressed_text, res
            except Exception:
                pass

        # 2. 尝试 Markdown 表格 / CSV 文本识别
        text_res = GcfTabularCodec.encode_tabular_text(text, config=self.config)
        if text_res.is_compressed:
            return text_res.compressed_text, text_res

        return text, None

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        total_compressed = 0
        total_saved_chars = 0

        for msg in context.messages:
            if isinstance(msg.content, str):
                orig = msg.content
                compressed, res = self._compress_string_content(orig)
                if res and res.is_compressed:
                    msg.content = compressed
                    total_compressed += 1
                    total_saved_chars += res.saved_chars
            elif isinstance(msg.content, list):
                # 处理多模态文本块
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "text" and "text" in block:
                        orig_text = str(block["text"])
                        comp_text, block_res = self._compress_string_content(orig_text)
                        if block_res and block_res.is_compressed:
                            block["text"] = comp_text
                            total_compressed += 1
                            total_saved_chars += block_res.saved_chars

        if total_compressed > 0:
            existing_saved = int(context.metadata.get("gcf_tabular_saved_chars", 0))
            existing_count = int(context.metadata.get("gcf_tabular_compressed_count", 0))
            context.metadata["gcf_tabular_saved_chars"] = existing_saved + total_saved_chars
            context.metadata["gcf_tabular_compressed_count"] = existing_count + total_compressed
            logger.debug(
                " [GcfTabularCompress] 成功压缩 %d 处表格，节省 %d 字符",
                total_compressed,
                total_saved_chars,
            )

        return context
