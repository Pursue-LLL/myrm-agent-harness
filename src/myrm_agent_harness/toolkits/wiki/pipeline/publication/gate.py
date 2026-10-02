"""Deterministic publication routing gate for concept writes.

[INPUT]
- .publish::ArticlePublishOutcome, publish_concept_article (POS: WPG publish funnel)
- ..core.frontmatter_contract::assert_valid_wiki_frontmatter (POS: fail-fast frontmatter contract)
- ..pending::WikiPendingEditsManager (POS: HITL staging; lazy import to avoid import cycle)

[OUTPUT]
- PublicationOrigin, PublicationDecision, PublicationRouteResult
- evaluate_publication_decision, route_concept_publication

[POS]
确定性发布路由门禁（fail-closed）。LLM 来源写入（agent 工具、chat 捕获）一律
进待审箱等待人工审核；仅人工发起的 settings 写入直发。未知来源一律视为待审。
人审通过后的路径（pending approve、synthesis backlinks）与确定性维护修复
（linter、evidence re-anchor）按设计保持直发，不经由此门禁。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    assert_valid_wiki_frontmatter,
)
from myrm_agent_harness.toolkits.wiki.pipeline.publication.publish import (
    ArticlePublishOutcome,
    publish_concept_article,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


class PublicationOrigin(StrEnum):
    """Origin of a concept write, deciding its publication route."""

    AGENT = "agent"
    HUMAN = "human"


class PublicationDecision(StrEnum):
    AUTO_PUBLISH = "auto_publish"
    STAGE_PENDING = "stage_pending"


@dataclass(frozen=True, slots=True)
class PublicationRouteResult:
    decision: PublicationDecision
    pending_edit_id: int | None = None
    publish_outcome: ArticlePublishOutcome | None = None


def evaluate_publication_decision(origin: PublicationOrigin | str) -> PublicationDecision:
    """Deterministic fail-closed routing: only known human origins auto-publish."""
    if origin == PublicationOrigin.HUMAN:
        return PublicationDecision.AUTO_PUBLISH
    return PublicationDecision.STAGE_PENDING


async def route_concept_publication(
    structure: WikiStructure,
    indexer: WikiIndexer | None,
    concept_name: str,
    content: str,
    *,
    origin: PublicationOrigin | str,
    source_files: list[str] | None = None,
    provenance: str | None = None,
) -> PublicationRouteResult:
    """Route a concept write through the deterministic gate.

    LLM origins stage a pending draft for human review; human origins publish
    directly through the WPG funnel. Staged content is validated up front so
    callers get immediate feedback instead of approve-time surprises.
    """
    if evaluate_publication_decision(origin) is PublicationDecision.STAGE_PENDING:
        assert_valid_wiki_frontmatter(content)

        # Lazy import: pending imports this publication package (import cycle).
        from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager

        pending_edit_id = await WikiPendingEditsManager(structure, indexer=indexer).stage_pending_edit(
            concept_name,
            content,
            source_files=source_files,
            provenance=provenance,
        )
        return PublicationRouteResult(
            decision=PublicationDecision.STAGE_PENDING,
            pending_edit_id=pending_edit_id,
        )

    publish_outcome = await publish_concept_article(structure, indexer, concept_name, content)
    return PublicationRouteResult(
        decision=PublicationDecision.AUTO_PUBLISH,
        publish_outcome=publish_outcome,
    )
