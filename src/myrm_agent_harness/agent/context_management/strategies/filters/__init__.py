"""Filters module.

提供任务感知的混合过滤策略：
- StructuralFilter: 结构化数据过滤器（JSON/XML/代码/CSV/YAML/日志）
- SemanticFilter: 语义过滤器（HTML/Markdown/纯文本）

特性：
- 智能内容类型检测
- 动态读取建议生成
- LLM 调用超时和重试机制
- 优雅降级处理
"""

from .base import (
    SEMANTIC_CONTENT_TYPES,
    STRUCTURAL_CONTENT_TYPES,
    BaseFilter,
    ContentType,
    FilterContext,
    FilterResult,
    detect_content_type,
    generate_smart_read_suggestions,
)
from .semantic_filter import SemanticFilter
from .structural_filter import StructuralFilter

__all__ = [
    "SEMANTIC_CONTENT_TYPES",
    # 内容类型常量
    "STRUCTURAL_CONTENT_TYPES",
    # 基类和数据结构
    "BaseFilter",
    "ContentType",
    "FilterContext",
    "FilterResult",
    "SemanticFilter",
    # 过滤器实现
    "StructuralFilter",
    # 工具函数
    "detect_content_type",
    "generate_smart_read_suggestions",
]
