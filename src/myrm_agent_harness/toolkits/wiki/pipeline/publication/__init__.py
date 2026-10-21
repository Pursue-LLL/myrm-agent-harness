"""Wiki publication gate — single write path for published concept pages.

[INPUT]
- .gate::PublicationOrigin, PublicationDecision, PublicationRouteResult, evaluate_publication_decision, route_concept_publication (POS: deterministic publish routing)
- .path_change::ConceptPathMapping, reindex_concepts_after_move (POS: concept move reindexing)
- .publish::ArticlePublishOutcome, publish_concept_article, repair_publication_status (POS: WPG publish SSOT)
- .stale_guard::StalePendingApprovalError, demote_stale_published_article, sources_newer_than_article (POS: stale guard and demotion)

[OUTPUT]
- ArticlePublishOutcome, ConceptPathMapping, PublicationDecision, PublicationOrigin, PublicationRouteResult, StalePendingApprovalError, demote_stale_published_article, evaluate_publication_decision, publish_concept_article, reindex_concepts_after_move, repair_publication_status, route_concept_publication, sources_newer_than_article

[POS]
Wiki Publication Gate 模块入口。提供概念页面发布、确定性发布路由、过时降级与重命名重索引统一门面。
"""

from .gate import (
    PublicationDecision,
    PublicationOrigin,
    PublicationRouteResult,
    evaluate_publication_decision,
    route_concept_publication,
)
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
    "PublicationDecision",
    "PublicationOrigin",
    "PublicationRouteResult",
    "StalePendingApprovalError",
    "demote_stale_published_article",
    "evaluate_publication_decision",
    "publish_concept_article",
    "reindex_concepts_after_move",
    "repair_publication_status",
    "route_concept_publication",
    "sources_newer_than_article",
]
