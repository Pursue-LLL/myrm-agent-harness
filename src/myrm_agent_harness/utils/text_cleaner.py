"""文本清理工具

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- re::re (POS: Python 正则表达式库)

[OUTPUT]
- clean_search_snippet(): 清理搜索结果摘要（去除空行、多余空格等）
- clean_full_content(): 深度清理完整内容（去除统计信息、导航、广告等噪音）
- COMPILED_PATTERNS: 预编译的正则模式（提升性能）

[POS]
Text cleaning utilities. Removes noise and irrelevant information from content to improve quality.

"""

import logging
import re

logger = logging.getLogger(__name__)

# 预编译常用正则模式以提升性能
COMPILED_PATTERNS = {
    "stats_line": re.compile(r"^\s*[\d.万千百十]+\s+\d+\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*$", re.MULTILINE),
    "whitespace": re.compile(r"[ \t]+"),
    "header": re.compile(r"^\s*(#{1,6})\s*(.+)$"),
}


def clean_search_snippet(snippet: str) -> str:
    """对搜索结果snippet进行基本的清理

    Args:
        snippet: 原始搜索结果摘要

    Returns:
        清理后的摘要内容
    """
    if not snippet:
        return ""

    # 1. 将多个换行符替换为单个换行符
    snippet = re.sub(r"\n+", "\n", snippet)

    # 2. 去除每行首尾的空白字符
    lines = [line.strip() for line in snippet.split("\n")]

    # 3. 去除空行
    lines = [line for line in lines if line]

    # 4. 去除行内多余空格
    lines = [re.sub(r"\s+", " ", line) for line in lines]

    # 重新组合内容，使用单个换行符分隔
    return "\n".join(lines)


def _is_code_block_marker(line: str) -> bool:
    """检查是否为代码块标记"""
    stripped = line.strip()
    return stripped == "```" or stripped.startswith("```")


def _remove_useless_patterns(content: str) -> str:
    """移除常见的无用内容模式（版权、统计信息等）"""
    # 移除统计信息行
    content = COMPILED_PATTERNS["stats_line"].sub("", content)

    # 批量移除无用模式
    useless_patterns = [
        r"版权声明.*?转载请.*?。",
        r"未经.*?授权.*?禁止.*?转载",
        r"CC \d+\.\d+ BY.*?版权",
        r"©\s*\d{4}.*?版权所有",
        r"All rights reserved",
        r"发布于\s*\d{4}-\d{2}-\d{2}",
        r"[\d.万千百十kK]+\s*阅读(?=\s|$)",
        r"\d+\s*(点赞|收藏|评论|转发|关注|喜欢)(?=\s|$)",
        r"^\s*(分享到|关注我|点击关注|扫码订阅).*?(?=\n|$)",
    ]

    flags = re.MULTILINE | re.IGNORECASE
    for pattern in useless_patterns:
        content = re.sub(pattern, "", content, flags=flags)

    return content


def _clean_formatting(content: str) -> str:
    """清理格式，彻底清理空行和空白字符

    性能优化：单次遍历完成标题规范化、列表规范化和格式清理
    """
    # 标准化换行符
    content = re.sub(r"\r\n|\r", "\n", content)

    # Footer和推荐文章的关键词列表
    unwanted_keywords = [
        "用户登录",
        "用户注册",
        "返回顶部",
        "关注我们",
        "联系我们",
        "版权所有",
        "备案号",
        "ICP",
        "助手",
        "客服",
        "最新工具",
        "最新文章",
        "热门推荐",
        "相关推荐",
        "推荐阅读",
        "热门文章",
        "最新推荐",
        "为您推荐",
        "猜你喜欢",
        "相关产品",
        "相关链接",
        "相关文章",
        "上一篇",
        "下一篇",
        "上一页",
        "下一页",
    ]

    lines = []
    in_code_block = False

    # 使用预编译的正则模式（性能优化）
    whitespace_pattern = COMPILED_PATTERNS["whitespace"]
    header_pattern = COMPILED_PATTERNS["header"]

    for line in content.split("\n"):
        # 检测代码块标记
        if _is_code_block_marker(line):
            in_code_block = not in_code_block
            lines.append(line.strip())
            continue

        # 在代码块内保留原始行（含缩进）
        if in_code_block:
            lines.append(line)
            continue

        # 代码块外：规范化 + 清理（单次处理）

        # 1. 规范化Markdown标题
        header_match = header_pattern.match(line)
        if header_match:
            _, title_text = header_match.groups()
            normalized_header = f"{header_match.group(1)} {title_text}"
            lines.append(normalized_header)
            continue

        # 4. 普通行清理
        stripped = line.strip()
        if stripped:
            # 过滤包含unwanted关键词的短文本行
            if len(stripped) < 20 and any(keyword in stripped for keyword in unwanted_keywords):
                continue

            # 清理行内多余空格
            cleaned_line = whitespace_pattern.sub(" ", stripped)
            lines.append(cleaned_line)
        elif lines and lines[-1]:  # 在有内容的行之间保留一个空行
            lines.append("")

    content = "\n".join(lines)

    # 清理多余的换行：多个连续换行保留为2个换行（\n\n）
    # 匹配3个或更多换行（可能包含空白字符），替换为2个换行
    content = re.sub(r"\n(?:\s*\n){2,}", "\n\n", content)

    return content.strip()


def clean_text(text: str) -> str:
    """智能清理文本内容，去除无用信息和噪音

    采用上下文感知的清理算法，既不会误清理有用内容，也不会放过无用内容

    Args:
        text: 原始文本

    Returns:
        清理后的文本
    """
    if not text:
        return ""

    # 检测并过滤乱码内容（避免浪费token）
    # 如果文本包含大量乱码字符（如�），可能是编码问题，返回空字符串
    if len(text) > 100:  # 只对长文本检查
        # 统计乱码字符比例
        garbled_count = text.count("�")
        # 如果乱码比例超过5%，认为是编码错误
        if garbled_count / len(text) > 0.05:
            return ""  # 返回空字符串，会被后续流程过滤掉

    # 简化为两阶段清理策略
    text = _remove_useless_patterns(text)
    text = _clean_formatting(text)

    return text


def clean_document_content(page_content: str) -> str:
    """清理文档的原始内容

    Args:
        page_content: 文档的page_content（可能包含或不包含front matter）

    Returns:
        清理后的纯内容
    """
    # 提取原始内容（去除可能的 front matter）
    content = page_content
    if page_content.startswith("---\n"):
        parts = page_content.split("\n---\n", 1)
        if len(parts) == 2:
            content = parts[1]

    # 应用清理逻辑
    return clean_text(content)
