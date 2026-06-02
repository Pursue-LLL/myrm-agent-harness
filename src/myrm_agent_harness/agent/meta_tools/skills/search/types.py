"""技能搜索模块的共享类型定义

[INPUT]
- (none)

[OUTPUT]
- SearchMetadata: class — Search Metadata
- SkillSearchResult: class — Skill Search Result

[POS]
Provides SearchMetadata, SkillSearchResult.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SKILL_SEARCH_TOP_K", "SearchMetadata", "SkillSearchResult"]

SKILL_SEARCH_TOP_K = 5


@dataclass(frozen=True)
class SearchMetadata:
    """搜索元数据，记录搜索过程中的异常和降级信息"""

    bm25_failed: bool = False
    embedding_failed: bool = False
    degraded: bool = False


@dataclass(frozen=True)
class SkillSearchResult:
    """搜索结果条目"""

    name: str
    description: str
    score: float
    metadata: SearchMetadata | None = None
