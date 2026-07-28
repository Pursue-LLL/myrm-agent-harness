"""Publish concept articles through a single validated write + index path.

[INPUT]
..core.frontmatter_contract (POS: type + publish_status validation)
..core.structure::WikiStructure (POS: vault paths)
..retrieval.indexer::WikiIndexer (POS: FTS/Qdrant upsert)

[OUTPUT]
publish_concept_article, repair_publication_status, ArticlePublishOutcome

[POS]
WPG-MVP: all published concept writes and indexer upserts go through here.
Pending SQLite drafts are approved via this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    assert_valid_wiki_frontmatter,
    ensure_published_frontmatter,
    repair_publication_on_disk,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = logging.getLogger(__name__)


class ArticlePublishOutcome(StrEnum):
    PUBLISHED = "published"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PublicationRepairResult:
    files_scanned: int
    files_repaired: int
    files_skipped: int
    files_skipped_intentional_drafts: int
    reindexed: int
    errors: tuple[str, ...] = ()


async def publish_concept_article(
    structure: WikiStructure,
    indexer: WikiIndexer | None,
    concept_name: str,
    content: str,
) -> ArticlePublishOutcome:
    """Validate frontmatter, stamp publish_status=published, write file, upsert search index."""
    assert_valid_wiki_frontmatter(content)
    published_content = ensure_published_frontmatter(content)

    article_path = structure.get_concept_file_path(concept_name)
    article_path.write_text(published_content, encoding="utf-8")

    if indexer is None:
        from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

        indexer = WikiIndexer(structure)

    await indexer.upsert(concept_name, published_content)
    edge_result = indexer.extract_and_upsert_edges(concept_name, published_content)
    if hasattr(edge_result, "__await__"):
        await edge_result

    logger.info("Published wiki concept: %s", concept_name)
    return ArticlePublishOutcome.PUBLISHED


async def repair_publication_status(
    structure: WikiStructure,
    indexer: WikiIndexer | None,
) -> PublicationRepairResult:
    """Grandfather missing publish_status to published; preserve intentional draft/blocked pages."""
    disk_result = repair_publication_on_disk(structure)
    reindexed = 0
    errors = list(disk_result.errors)

    if indexer is None:
        from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

        indexer = WikiIndexer(structure)

    for concept_path in structure.list_concepts():
        rel = str(concept_path.relative_to(structure.concepts_dir).with_suffix("")).replace("\\", "/")
        try:
            content = concept_path.read_text(encoding="utf-8")
            await indexer.upsert(rel, content)
            edge_result = indexer.extract_and_upsert_edges(rel, content)
            if hasattr(edge_result, "__await__"):
                await edge_result
            reindexed += 1
        except OSError as exc:
            errors.append(f"{concept_path}: {exc}")

    return PublicationRepairResult(
        files_scanned=disk_result.files_scanned,
        files_repaired=disk_result.files_repaired,
        files_skipped=disk_result.files_skipped_published,
        files_skipped_intentional_drafts=disk_result.files_skipped_intentional_draft,
        reindexed=reindexed,
        errors=tuple(errors),
    )
