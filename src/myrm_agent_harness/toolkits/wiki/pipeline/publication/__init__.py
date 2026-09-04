"""Wiki publication gate — single write path for published concept pages.

[INPUT]
- .path_change::ConceptPathMapping, reindex_concepts_after_move (POS: concept move reindexing)
- .publish::ArticlePublishOutcome, publish_concept_article, repair_publication_status (POS: WPG publish SSOT)
- .stale_guard::StalePendingApprovalError, demote_stale_published_article, sources_newer_than_article (POS: stale guard and demotion)

[OUTPUT]
- ArticlePublishOutcome, ConceptPathMapping, StalePendingApprovalError, demote_stale_published_article, publish_concept_article, reindex_concepts_after_move, repair_publication_status, sources_newer_than_article

[POS]
Wiki Publication Gate 模块入口。提供概念页面发布、过时降级与重命名重索引统一门面。
"""

from .path_change import ConceptPathMapping, reindex_concepts_after_move
from .publish import ArticlePublishOutcome, publish_concept_article, repair_publication_status
from .stale_guard import (
    StalePendingApprovalError,
    demote_stale_published_article,
    sources_newer_than_article,
)

__all__ = [
    "ArticlePublishOutcome",
    "ConceptPathMapping",
    "StalePendingApprovalError",
    "demote_stale_published_article",
    "publish_concept_article",
    "reindex_concepts_after_move",
    "repair_publication_status",
    "sources_newer_than_article",
]
