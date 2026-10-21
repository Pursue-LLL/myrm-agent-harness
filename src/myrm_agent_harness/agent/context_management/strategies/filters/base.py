"""过滤器基类定义

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- abc::ABC, abstractmethod (POS: Python 抽象基类)
- dataclasses::dataclass, field (POS: Python 数据类装饰器)
- typing::Literal (POS: Python 类型提示)

[OUTPUT]
- ContentType: 内容类型定义（Literal 类型）
- STRUCTURAL_CONTENT_TYPES: 结构化内容类型集合（JSON/XML/代码等）
- SEMANTIC_CONTENT_TYPES: 语义内容类型集合（HTML/Markdown/文本）
- FilterContext: 过滤上下文数据类
- FilterResult: 过滤结果数据类
- BaseFilter: 过滤器抽象基类
- detect_content_type: 内容类型检测函数

[POS]
Filter base class definition. Defines the filter interface (BaseFilter), data structures (FilterContext, FilterResult), and content-type detection logic for distinguishing structured vs. semantic content.

"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

# 扩展内容类型：添加 CSV、YAML、LOG 类型
ContentType = Literal["json", "html", "xml", "markdown", "code", "csv", "yaml", "log", "plain_text"]

# 结构化内容类型（使用 StructuralFilter，不需要 LLM）
STRUCTURAL_CONTENT_TYPES: frozenset[ContentType] = frozenset({"json", "xml", "code", "csv", "yaml", "log"})

# 语义内容类型（使用 SemanticFilter + LLM）
SEMANTIC_CONTENT_TYPES: frozenset[ContentType] = frozenset({"html", "markdown", "plain_text"})


@dataclass
class FilterContext:
    """过滤上下文

    Attributes:
        content: 原始内容
        file_path: 存储路径
        content_type: 内容类型
        user_query: 用户查询（任务上下文，可选）
        tool_name: 工具名称（可选）
    """

    content: str
    file_path: str
    content_type: ContentType
    user_query: str = ""
    tool_name: str = ""


@dataclass
class FilterResult:
    """过滤结果

    Attributes:
        file_path: 存储路径
        content_type: 内容类型
        total_lines: 总行数
        total_chars: 总字符数
        estimated_tokens: 估计 tokens
        summary: 核心摘要（任务相关的关键信息）
        structure_overview: 结构概览（数据结构、键列表等）
        read_suggestions: 读取建议列表
        llm_generated: 摘要是否由 LLM 生成（用于错误处理时的降级展示）
    """

    file_path: str
    content_type: ContentType
    total_lines: int
    total_chars: int
    estimated_tokens: int
    summary: str
    structure_overview: str = ""
    read_suggestions: list[str] = field(default_factory=list)
    llm_generated: bool = False


class BaseFilter(ABC):
    """过滤器基类

    所有过滤器必须实现 filter 方法。
    """

    @abstractmethod
    async def filter(self, context: FilterContext) -> FilterResult:
        """执行过滤

        Args:
            context: 过滤上下文

        Returns:
            FilterResult 过滤结果
        """
        pass


def detect_content_type(content: str) -> ContentType:
    """检测内容类型

    检测顺序（按特异性从高到低）：
    1. JSON - 尝试解析
    2. YAML - 检测 YAML 特征
    3. CSV - 检测 CSV 特征
    4. LOG - 检测日志格式
    5. HTML - 检测 HTML 标签
    6. XML - 检测 XML 声明或标签
    7. Markdown - 检测 Markdown 特征
    8. Code - 检测代码特征
    9. Plain text - 默认

    Args:
        content: 要检测的内容

    Returns:
        检测到的内容类型
    """
    content_stripped = content.strip()
    first_500 = content[:500]
    first_lines = content_stripped.split("\n")[:10]

    # 1. JSON - 最精确的检测（尝试解析）
    if content_stripped.startswith("{") or content_stripped.startswith("["):
        try:
            json.loads(content_stripped)
            return "json"
        except json.JSONDecodeError:
            pass

    # 2. YAML - 检测 YAML 特征
    # YAML 特征：--- 开头、key: value 格式、没有 = 号
    if _is_yaml_content(content_stripped, first_lines):
        return "yaml"

    # 3. CSV - 检测 CSV 特征
    if _is_csv_content(first_lines):
        return "csv"

    # 4. LOG - 检测日志格式（带时间戳的行）
    if _is_log_content(first_lines):
        return "log"

    # 5. HTML - 检测 HTML 标签
    if "<html" in content.lower() or "<!doctype html" in content.lower():
        return "html"

    # 6. XML - 检测 XML 声明或标签（但不是 HTML）
    if content_stripped.startswith("<?xml"):
        return "xml"
    # 检测 XML 标签但排除 HTML 和常见代码（如 JSX）
    if content_stripped.startswith("<") and ">" in content_stripped[:100]:
        # 排除 JSX/TSX（常见代码标签）
        jsx_patterns = ["<div", "<span", "<button", "<input", "<form"]
        if not any(pattern in first_500 for pattern in jsx_patterns):
            return "xml"

    # 7. Markdown - 检测 Markdown 特征
    if content.startswith("#") or "\n## " in content or "\n```" in content:
        return "markdown"

    # 8. 代码（启发式检测）
    code_indicators = ["def ", "class ", "import ", "function ", "const ", "let ", "var ", "func ", "pub fn "]
    if any(indicator in first_500 for indicator in code_indicators):
        return "code"

    return "plain_text"


def _is_yaml_content(content_stripped: str, first_lines: list[str]) -> bool:
    """检测是否为 YAML 内容"""
    # YAML 文档分隔符
    if content_stripped.startswith("---"):
        return True

    # 计算符合 YAML key: value 格式的行数
    yaml_pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*:\s*")
    yaml_line_count = sum(1 for line in first_lines if yaml_pattern.match(line))

    # 如果超过一半的非空行符合 YAML 格式，且没有 = 号（排除 INI 格式）
    non_empty_lines = [line for line in first_lines if line.strip()]
    return bool(
        non_empty_lines
        and yaml_line_count >= len(non_empty_lines) * 0.5
        and not any("=" in line for line in first_lines)
    )


def _is_csv_content(first_lines: list[str]) -> bool:
    """检测是否为 CSV 内容"""
    if len(first_lines) < 2:
        return False

    # 检测分隔符一致性
    for delimiter in [",", "\t", ";"]:
        counts = [line.count(delimiter) for line in first_lines[:5] if line.strip()]
        if counts and min(counts) >= 2 and max(counts) - min(counts) <= 1:
            return True

    return False


def _is_log_content(first_lines: list[str]) -> bool:
    """检测是否为日志内容（带时间戳的行）"""
    # 常见日志时间戳格式
    log_patterns = [
        r"^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}",  # ISO 格式
        r"^\[\d{4}-\d{2}-\d{2}",  # [2024-01-01 ...] 格式
        r"^\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}",  # Apache 日志格式
        r"^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}",  # Syslog 格式
    ]

    # 如果超过一半的行匹配日志格式
    match_count = 0
    for line in first_lines[:10]:
        if line.strip():
            for pattern in log_patterns:
                if re.match(pattern, line):
                    match_count += 1
                    break

    return match_count >= 3


def generate_smart_read_suggestions(file_path: str, total_lines: int, content_type: ContentType) -> list[str]:
    """生成智能读取建议

    根据内容大小和类型动态生成合适的读取建议。

    Args:
        file_path: 文件路径
        total_lines: 总行数
        content_type: 内容类型

    Returns:
        读取建议列表
    """
    suggestions = []

    # 根据内容大小动态调整行范围
    if total_lines <= 100:
        # 小文件：建议读全部
        suggestions.append(f'file_read_tool(paths=["{file_path}"])')
    elif total_lines <= 500:
        # 中等文件：建议读前 100 行
        suggestions.append(f'file_read_tool(paths=["{file_path}:1-100"])')
        suggestions.append(f'# For full content: file_read_tool(paths=["{file_path}"])')
    else:
        # 大文件：建议读前 50 行 + grep 搜索
        suggestions.append(f'file_read_tool(paths=["{file_path}:1-50"])')
        suggestions.append(f'# Search for specific content: grep_tool(pattern="keyword", path="{file_path}")')

    # 根据内容类型添加特定建议
    if content_type == "json":
        suggestions.append(
            f"# Process JSON with Python:\n"
            f"import json\n"
            f'with open("{file_path}") as f:\n'
            f" data = json.load(f)\n"
            f"print(len(data) if isinstance(data, list) else list(data.keys())[:10])"
        )
    elif content_type == "csv":
        suggestions.append(
            f'# Process CSV with pandas:\nimport pandas as pd\ndf = pd.read_csv("{file_path}")\nprint(df.head())'
        )
    elif content_type == "log":
        suggestions.append(f'# Search logs: grep_tool(pattern="ERROR|WARNING", paths=["{file_path}"])')
    elif content_type == "code":
        suggestions.append(f'# Find functions: grep_tool(pattern="def |function ", paths=["{file_path}"])')

    return suggestions
