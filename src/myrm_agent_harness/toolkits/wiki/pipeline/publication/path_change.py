"""Reindex concept articles after vault path changes (move/rename).

[INPUT]
- ..core.frontmatter_contract::validate_wiki_frontmatter (POS: type gate)
- ..core.structure::WikiStructure (POS: concept paths)
- ..retrieval.indexer::WikiIndexer (POS: delete + upsert)

[OUTPUT]
- ConceptPathMapping, reindex_concepts_after_move

[POS]
Frontmatter-aware reindex for wiki tree move/rename; preserves publish_status on disk; skips directory sidecars.
Synchronizes inbound links and wiki edges for referring concept articles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import validate_wiki_frontmatter
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

if TYPE_CHECKING:
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
    *,
    modified_referrers: Sequence[str | Path] = (),
) -> int:
    """Delete old index keys and upsert moved concept pages under their new paths.

    Also reindexes any referencing concepts whose inbound links were modified during refactoring.
    """
    reindexed = 0
    seen_paths: set[Path] = set()
    seen_concepts: set[str] = set()
    for mapping in mappings:
        await indexer.delete(mapping.old_concept)

        article_path = structure.get_concept_file_path(mapping.new_concept)
        if not article_path.exists():
            continue

        resolved = article_path.resolve()
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)

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
        seen_concepts.add(mapping.new_concept)
        reindexed += 1

    # Reindex referencing concepts whose content / wikilinks were updated
    for referrer in modified_referrers:
        if isinstance(referrer, Path):
            try:
                rel = referrer.relative_to(structure.concepts_dir)
                concept_name = str(rel.with_suffix("")).replace("\\", "/")
                file_path = referrer
            except ValueError:
                continue
        else:
            concept_name = str(referrer).strip().replace("\\", "/")
            if concept_name.endswith(".md"):
                concept_name = concept_name[:-3]
            file_path = structure.get_concept_file_path(concept_name)

        if not file_path.exists() or WikiStructure._is_directory_sidecar(file_path):
            continue

        resolved = file_path.resolve()
        if resolved in seen_paths or concept_name in seen_concepts:
            continue
        seen_paths.add(resolved)
        seen_concepts.add(concept_name)

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read referencing concept %s: %s", concept_name, exc)
            continue

        validation = validate_wiki_frontmatter(content)
        if not validation.ok:
            logger.warning(
                "Skipping reindex for referencing concept %s: %s",
                concept_name,
                "; ".join(validation.errors),
            )
            continue

        await indexer.upsert(concept_name, content)
        edge_result = indexer.extract_and_upsert_edges(concept_name, content)
        if hasattr(edge_result, "__await__"):
            await edge_result
        reindexed += 1

    return reindexed
