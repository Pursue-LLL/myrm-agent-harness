"""内容标准化处理器

在发往 LLM 之前，统一清理无效空行、不一致换行符，并剔除零宽字符。
这对于提高多轮对话的 Prompt Cache 命中率至关重要，防止微小的格式抖动导致 Cache Miss。

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain 消息基类)

[OUTPUT]
- NormalizeProcessor: class — Content Normalizer Processor

[POS]
Provides NormalizeProcessor.
"""

import re

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)

# 匹配 3 个或更多连续空行（包括带空格的空行）
_MULTIPLE_NEWLINES_RE = re.compile(r"\n\s*\n\s*\n+")


def normalize_content(content: str) -> str:
    """标准化文本内容

    1. 统一换行符为 \n
    2. 剔除零宽字符
    3. 将 3 个及以上的连续空行压缩为 2 个换行符（即 1 个空行）
    4. 去除首尾空白
    """
    if not content:
        return content

    # 1. 统一换行符
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # 2. 剔除零宽字符 (Zero-width space, Zero-width non-joiner, etc.)
    content = content.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")

    # 3. 压缩连续空行
    content = _MULTIPLE_NEWLINES_RE.sub("\n\n", content)

    # 4. 去除首尾空白
    return content.strip()


class NormalizeProcessor(BaseProcessor):
    """内容标准化处理器

    在 ExplicitCacheProcessor 之前运行，确保发往大模型的内容格式绝对一致。
    大幅提升多轮对话的 Cache 命中率。
    """

    @property
    def name(self) -> str:
        return "normalize"

    async def should_process(self, context: ProcessorContext) -> bool:
        # 始终执行标准化，成本极低且收益极高
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        normalized_count = 0

        for msg in context.messages:
            if isinstance(msg.content, str):
                original = msg.content
                normalized = normalize_content(original)
                if original != normalized:
                    msg.content = normalized
                    normalized_count += 1
            elif isinstance(msg.content, list):
                # 处理多模态/复杂内容块
                changed = False
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "text" and "text" in block:
                        original = block["text"]
                        normalized = normalize_content(original)
                        if original != normalized:
                            block["text"] = normalized
                            changed = True
                if changed:
                    normalized_count += 1

        if normalized_count > 0:
            logger.debug(" [Normalize] 规范化了 %d 条消息的格式", normalized_count)

        return context
