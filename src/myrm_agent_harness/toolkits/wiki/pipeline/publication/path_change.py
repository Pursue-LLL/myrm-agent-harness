"""Reindex concept articles after vault path changes (move/rename).

[INPUT]
..core.frontmatter_contract::validate_wiki_frontmatter (POS: type gate)
..core.structure::WikiStructure (POS: concept paths)
..retrieval.indexer::WikiIndexer (POS: delete + upsert)

[OUTPUT]
ConceptPathMapping, reindex_concepts_after_move

[POS]
Frontmatter-aware reindex for wiki tree move/rename; preserves publish_status on disk; skips directory sidecars.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import validate_wiki_frontmatter
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConceptPathMapping:
    old_concept: str
    new_concept: str


async def reindex_concepts_after_move(
    structure: WikiStructure,
    indexer: WikiIndexer,
    mappings: list[ConceptPathMapping],
) -> int:
    """Delete old index keys and upsert moved concept pages under their new paths."""
    reindexed = 0
    for mapping in mappings:
        await indexer.delete(mapping.old_concept)

        article_path = structure.get_concept_file_path(mapping.new_concept)
        if not article_path.exists():
            continue

        if WikiStructure._is_directory_sidecar(article_path):
            continue

        try:
            content = article_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read moved concept %s: %s", mapping.new_concept, exc)
            continue

        validation = validate_wiki_frontmatter(content)
        if not validation.ok:
            logger.warning(
                "Skipping reindex for moved concept %s: %s",
                mapping.new_concept,
                "; ".join(validation.errors),
            )
            continue

        await indexer.upsert(mapping.new_concept, content)
        edge_result = indexer.extract_and_upsert_edges(mapping.new_concept, content)
        if hasattr(edge_result, "__await__"):
            await edge_result
        reindexed += 1

    return reindexed
