"""Document 对象处理工具函数

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- langchain_core.documents::Document (POS: LangChain 文档类型)

[OUTPUT]
- parse_front_matter(): 解析 Front Matter（返回正文和元数据）
- extract_original_content(): 提取文档的原始内容（去除元信息）
- extract_clean_content_for_context(): 提取干净内容用于上下文（有条件保留 section）
- enhance_document_content(): 增强文档内容（添加标题、来源等元信息）

[POS]
Document object utilities. Provides LangChain Document front matter parsing, clean content extraction, and content enhancement.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.documents import Document

# 配置日志
logger = logging.getLogger(__name__)


def parse_front_matter(page_content: str) -> tuple[str, dict[str, str]]:
    """解析Front Matter，返回正文和元数据字典

    Args:
        page_content: 包含Front Matter的内容

    Returns:
        tuple: (正文内容, 元数据字典)
    """
    if not page_content:
        return "", {}

    content = page_content.strip()
    metadata = {}

    # 查找并解析Front Matter
    if content.startswith("---\n"):
        parts = content.split("---\n", 2)
        # 确保有两个分隔符，并且它们之间有内容
        if len(parts) >= 3:
            front_matter_raw = parts[1]
            main_content = parts[2].strip()

            # 解析Front Matter中的键值对
            for line in front_matter_raw.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip()

            return main_content, metadata

    # 如果没有找到有效的Front Matter，则返回原始内容和空元数据
    return content, {}


def extract_original_content(page_content: str) -> str:
    """从增强后的内容中只提取原始正文。

    此函数会查找并移除整个Front Matter块（---...---），
    只返回分隔符之后的核心内容。

    Args:
        page_content: 经过enhance_document_content处理的内容。

    Returns:
        纯净的原始正文内容。
    """
    main_content, _ = parse_front_matter(page_content)
    return main_content


def extract_clean_content_for_context(page_content: str) -> str:
    """从增强后的内容中提取上下文，有条件地保留 section。

    解析 Front Matter 并提取正文。如果 Front Matter 中包含 'section'，
    将其置于正文之前以保留结构信息；否则只返回纯净的正文。

    Args:
        page_content: 经过 enhance_document_content 处理的内容。

    Returns:
        清理后的正文，可能带有 section 信息的 Front Matter。
    """
    main_content, metadata = parse_front_matter(page_content)
    if "section" in metadata:
        return f"---\nsection: {metadata['section']}\n---\n\n{main_content}"
    return main_content


def enhance_document_content(doc: Document, section_path: str = "", save_original: bool = True) -> str:
    """增强文档内容，采用Markdown Front Matter风格将元信息置顶

    Args:
        doc: 要增强的文档对象
        section_path: 可选的章节路径信息
        save_original: 是否将原始内容保存到metadata中，用于后续去重

    Returns:
        增强后的内容字符串（Front Matter格式）
    """
    # 保存原始内容到metadata，用于融合阶段的去重
    if save_original and "original_content" not in doc.metadata:
        doc.metadata["original_content"] = doc.page_content

    # 提取关键元信息
    title = (doc.metadata.get("title") or "").strip()
    # 直接使用metadata中的URL（通常已经标准化，包含scheme，解码后）
    url = (doc.metadata.get("url") or "").strip()

    # 构建Front Matter风格的元信息头部
    front_matter_lines = []

    if title:
        front_matter_lines.append(f"title: {title}")

    if url:
        front_matter_lines.append(f"url: {url}")

    # 添加section信息(SmartMarkdownHeaderTextSplitter已处理过滤逻辑)
    if section_path:
        front_matter_lines.append(f"section: {section_path}")

    # 组装增强内容：Front Matter + 正文
    if front_matter_lines:
        front_matter = "\n".join(front_matter_lines)
        enhanced_content = f"---\n{front_matter}\n---\n\n{doc.page_content}"
    else:
        # 如果没有元信息，直接返回原内容
        enhanced_content = doc.page_content

    return enhanced_content
