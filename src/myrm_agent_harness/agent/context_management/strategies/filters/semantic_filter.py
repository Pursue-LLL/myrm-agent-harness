"""语义过滤器

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- base::BaseFilter, FilterContext, FilterResult (POS: 过滤器基类和数据结构)
- prompts::CONTENT_DESCRIPTION_PROMPT 等 (POS: LLM 提示词模板)
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM 基类)
- utils.text_utils::get_token_count (POS: Token 计数工具)

[OUTPUT]
- SemanticFilter: 语义过滤器类（使用 LLM 理解非结构化数据）

[POS]
Semantic filter. Uses LLM to describe the structure and key points of unstructured content (HTML/Markdown/plain text), guiding the model to read efficiently rather than replacing raw data.

"""

import asyncio
import json
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.text_utils import get_token_count

from .base import BaseFilter, ContentType, FilterContext, FilterResult, generate_smart_read_suggestions
from .prompts import (
    CONTENT_DESCRIPTION_PROMPT,
    HTML_DESCRIPTION_PROMPT,
    MARKDOWN_DESCRIPTION_PROMPT,
    PLAIN_TEXT_DESCRIPTION_PROMPT,
)

logger = get_agent_logger(__name__)

# 发送给 LLM 的最大内容长度（字符数）
MAX_CONTENT_LENGTH = 30000  # 减少长度，因为我们只需要描述结构

# LLM 调用超时时间（秒）
LLM_TIMEOUT_SECONDS = 30

# 最大重试次数
MAX_RETRIES = 1


class SemanticFilter(BaseFilter):
    """语义过滤器

    使用便宜 LLM 描述内容结构，帮助模型理解文件内容。

    健壮性特性：
    - 超时机制：LLM 调用超过 30 秒后自动降级
    - 重试机制：失败后最多重试 1 次
    - 优雅降级：LLM 失败时使用代码提取基础信息
    """

    def __init__(self, llm: BaseChatModel) -> None:
        """初始化语义过滤器

        Args:
            llm: 便宜的 LLM 客户端（如 GPT-4o-mini, Claude Haiku）
        """
        self.llm = llm

    async def filter(self, context: FilterContext) -> FilterResult:
        """执行语义过滤

        Args:
            context: 过滤上下文

        Returns:
            FilterResult 过滤结果
        """
        total_lines = len(context.content.splitlines())
        llm_generated = False

        # 尝试使用 LLM 生成描述
        description_data = await self._call_llm_with_retry(context)

        if description_data is not None:
            llm_generated = True
            summary = self._build_summary(context, description_data)
            structure_overview = self._build_structure_overview(context, description_data)
            # LLM 的读取建议
            reading_suggestion = description_data.get("reading_suggestion", "")
            extra_suggestions = [f" {reading_suggestion}"] if reading_suggestion else []
        else:
            # LLM 失败，使用降级描述（不展示 LLM 生成部分）
            summary = self._build_fallback_summary(context)
            structure_overview = self._build_fallback_structure(context)
            extra_suggestions = []

        # 使用智能读取建议
        read_suggestions = extra_suggestions + generate_smart_read_suggestions(
            file_path=context.file_path, total_lines=total_lines, content_type=context.content_type
        )

        return FilterResult(
            file_path=context.file_path,
            content_type=context.content_type,
            total_lines=total_lines,
            total_chars=len(context.content),
            estimated_tokens=get_token_count(context.content),
            summary=summary,
            structure_overview=structure_overview,
            read_suggestions=read_suggestions,
            llm_generated=llm_generated,
        )

    async def _call_llm_with_retry(self, context: FilterContext) -> dict[str, object] | None:
        """带重试和超时的 LLM 调用

        Args:
            context: 过滤上下文

        Returns:
            LLM 响应解析后的字典，如果失败返回 None
        """
        # 截断内容以控制成本
        truncated_content = context.content[:MAX_CONTENT_LENGTH]
        if len(context.content) > MAX_CONTENT_LENGTH:
            truncated_content += f"\n\n[... content truncated, original length: {len(context.content)} chars ...]"

        # 选择合适的 prompt
        prompt = self._select_prompt(context.content_type)
        formatted_prompt = prompt.format(content=truncated_content)

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                # 使用超时机制调用 LLM
                response = await asyncio.wait_for(
                    self.llm.ainvoke([HumanMessage(content=formatted_prompt)]), timeout=LLM_TIMEOUT_SECONDS
                )
                # response.content 可能是 str 或 list，统一转为 str
                response_text = response.content if isinstance(response.content, str) else str(response.content)
                return self._parse_llm_response(response_text)

            except TimeoutError:
                logger.warning(f"LLM call timeout (attempt {attempt + 1}/{MAX_RETRIES + 1})")
                last_error = TimeoutError("LLM call timed out")

            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt + 1}/{MAX_RETRIES + 1}): {type(e).__name__}: {e}")
                last_error = e

        # 所有重试都失败
        logger.warning(f"All LLM attempts failed, falling back to code extraction. Last error: {last_error}")
        return None

    def _select_prompt(self, content_type: ContentType) -> str:
        """选择合适的 prompt 模板"""
        return {
            "html": HTML_DESCRIPTION_PROMPT,
            "markdown": MARKDOWN_DESCRIPTION_PROMPT,
            "plain_text": PLAIN_TEXT_DESCRIPTION_PROMPT,
        }.get(content_type, CONTENT_DESCRIPTION_PROMPT)

    def _parse_llm_response(self, response_content: str) -> dict[str, object]:
        """解析 LLM 响应"""
        content = response_content

        # 尝试提取 JSON
        try:
            # 查找 JSON 块
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > start:
                json_str = content[start:end]
                return dict(json.loads(json_str))
        except json.JSONDecodeError:
            logger.warning("LLM response JSON parsing failed")

        # 解析失败，返回原始内容作为描述
        return {"main_topic": content[:200], "structure": "unknown"}

    def _build_fallback_summary(self, context: FilterContext) -> str:
        """LLM 失败时构建降级摘要（使用代码提取）"""
        content = context.content
        lines = content.splitlines()

        if context.content_type == "html":
            # 提取 title
            title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
            title = title_match.group(1).strip() if title_match else "Unknown"
            return f"[HTML] {title}"

        elif context.content_type == "markdown":
            # 提取第一个标题
            header_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            title = header_match.group(1) if header_match else "Markdown Document"
            return f"[Markdown] {title}"

        else:
            # 纯文本
            preview = " ".join(lines[:2])[:80]
            return f"[Text] {len(lines)} lines - {preview}..."

    def _build_fallback_structure(self, context: FilterContext) -> str:
        """LLM 失败时构建降级结构概览（使用代码提取）"""
        content = context.content
        lines = content.splitlines()

        if context.content_type == "html":
            # 提取标签统计
            tags = re.findall(r"<(\w+)[^>]*>", content)
            tag_counts: dict[str, int] = {}
            for tag in tags[:1000]:  # 限制解析数量
                tag = tag.lower()
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

            structure_lines = ["HTML elements:"]
            sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
            for tag, count in sorted_tags[:10]:
                structure_lines.append(f" - <{tag}>: {count}")
            return "\n".join(structure_lines)

        elif context.content_type == "markdown":
            # 提取所有标题作为目录
            headers = re.findall(r"^(#{1,3})\s+(.+)$", content, re.MULTILINE)
            if headers:
                structure_lines = ["Table of contents:"]
                for level, title in headers[:10]:
                    structure_lines.append(f" {level} {title}")
                if len(headers) > 10:
                    structure_lines.append(f" ... and {len(headers) - 10} more sections")
                return "\n".join(structure_lines)
            return "No headers found"

        else:
            # 纯文本 - 显示前几行预览
            preview_lines = lines[:5]
            structure_lines = ["Content preview:"]
            for i, line in enumerate(preview_lines):
                structure_lines.append(f" {i + 1}: {line[:80]}")
            if len(lines) > 5:
                structure_lines.append(f" ... and {len(lines) - 5} more lines")
            return "\n".join(structure_lines)

    def _build_summary(self, context: FilterContext, description_data: dict[str, object]) -> str:
        """构建摘要"""
        main_topic = description_data.get("main_topic", "")
        content_type = description_data.get(
            "content_type", description_data.get("page_type", description_data.get("document_type", ""))
        )

        if context.content_type == "html":
            page_title = description_data.get("page_title", "")
            if page_title:
                return f"[HTML] {page_title} - {main_topic}"
            return f"[HTML] {main_topic}"

        elif context.content_type == "markdown":
            doc_title = description_data.get("document_title", "")
            if doc_title:
                return f"[Markdown] {doc_title} - {main_topic}"
            return f"[Markdown] {main_topic}"

        else:
            if content_type:
                return f"[{content_type}] {main_topic}"
            return str(main_topic) if main_topic else "Content description unavailable"

    def _build_structure_overview(self, context: FilterContext, description_data: dict[str, object]) -> str:
        """构建结构概览"""
        lines = []

        # 结构信息
        structure = description_data.get("structure", "")
        if structure:
            lines.append(f"Structure: {structure}")

        # HTML 特有信息
        if context.content_type == "html":
            main_sections = description_data.get("main_sections", [])
            if main_sections and isinstance(main_sections, list):
                lines.append("Main sections:")
                for section in main_sections[:5]:
                    lines.append(f" - {section}")

            has_links = description_data.get("has_useful_links")
            if has_links:
                lines.append("Contains useful links: Yes")

        # Markdown 特有信息
        elif context.content_type == "markdown":
            toc = description_data.get("table_of_contents", [])
            if toc and isinstance(toc, list):
                lines.append("Table of contents:")
                for heading in toc[:10]:
                    lines.append(f" {heading}")

        # 纯文本特有信息
        else:
            patterns = description_data.get("notable_patterns", [])
            if patterns and isinstance(patterns, list):
                lines.append("Notable patterns:")
                for pattern in patterns[:3]:
                    lines.append(f" - {pattern}")

            key_sections = description_data.get("key_sections", [])
            if key_sections and isinstance(key_sections, list):
                lines.append("Key sections:")
                for section in key_sections[:5]:
                    lines.append(f" - {section}")

        return "\n".join(lines) if lines else "No structure information available"
