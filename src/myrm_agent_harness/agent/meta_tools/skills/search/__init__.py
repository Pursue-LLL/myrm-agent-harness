"""Skill search module.

提供自适应的技能搜索功能。
当技能数量超过阈值时，使用搜索引擎替代完全内联。

支持两种搜索模式：
1. BM25 词法搜索（默认）：通过 Prompt 引导多语言查询
2. Embedding 语义搜索（可选）：天然跨语言理解，需配置 embedding_config
"""

from .query_expansion import QueryExpander
from .types import SKILL_SEARCH_TOP_K, SkillSearchResult

__all__ = [
    "SKILL_SEARCH_TOP_K",
    "QueryExpander",
    "SkillSearchResult",
]
