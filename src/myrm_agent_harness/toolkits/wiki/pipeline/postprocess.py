"""Post-compilation processing: index, backlinks, and metadata persistence.

[INPUT]
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- ..core.config::WikiConfig (POS: Wiki configuration center)
- ..core.types::ConceptInfo, WikiMetadata (POS: Wiki toolkit type definitions)
- ..core.claims_contract (POS: raw hash metadata keys and collectors, metadata merge writer)
- ..core.link_resolver::WikiLinkResolver, concept_link_name (POS: page identity of a link)
- ..core.related_links::merge_related_links (POS: the only writer of a page's Related Concepts section)

[OUTPUT]
- generate_backlinks: Add each concept's related concepts to its Related Concepts section (Obsidian format)
- save_metadata: Persist compilation metadata with portable SHA256 raw snapshots; keys other writers keep in the file stay

[POS]
Post-compilation steps: backlink creation and metadata persistence after concept
extraction and article generation. OKF index/log/hot live in cognitive_map/.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..core.claims_contract import (
    LAST_COMPILE_RAW_HASHES_KEY,
    collect_raw_content_hashes,
    write_wiki_metadata_merge,
)
from ..core.link_resolver import WikiLinkResolver, concept_link_name
from ..core.related_links import merge_related_links
from ..core.structure import WikiStructure
from ..core.types import ConceptInfo, WikiMetadata

if TYPE_CHECKING:
    from ..core.config import WikiConfig
    from ..retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)


async def generate_backlinks(
    structure: WikiStructure,
    config: WikiConfig,
    concepts: list[ConceptInfo],
    indexer: WikiIndexer | None = None,
) -> int:
    """Add each concept's related concepts to its Related Concepts section (Obsidian format).

    Idempotent: a related concept the section already links is not added again, and a page
    that gains nothing is neither rewritten nor re-indexed. Returns the number of links added.
    """
    backlinks_count = 0
    resolver = WikiLinkResolver(structure)

    for concept in concepts:
        if not concept.related_concepts:
            continue

        article_path = structure.get_concept_file_path(concept.name)
        if not article_path.exists():
            continue

        try:
            content = article_path.read_text(encoding="utf-8")
            merged, added = merge_related_links(
                content,
                concept.related_concepts,
                source=concept_link_name(article_path, structure.concepts_dir),
                resolver=resolver,
            )
            if not added:
                continue

            article_path.write_text(merged, encoding="utf-8")
            backlinks_count += added

            if indexer is None:
                from ..retrieval.indexer import WikiIndexer

                indexer = WikiIndexer(structure, config)
            indexer.extract_and_upsert_edges(concept.name, merged)

        except Exception as e:
            logger.error(f"Failed to add backlinks for {concept.name}: {e}")

    return backlinks_count


async def save_metadata(
    structure: WikiStructure,
    concepts_count: int,
    articles_count: int,
) -> None:
    """Save wiki metadata including portable SHA256 raw snapshots for incremental compile."""
    raw_files = structure.list_raw_files()
    raw_hashes = collect_raw_content_hashes(structure)

    metadata = WikiMetadata(
        last_compile_time=datetime.now(UTC),
        total_concepts=concepts_count,
        total_articles=articles_count,
        total_raw_files=len(raw_files),
    )

    metadata_path = structure.get_wiki_metadata_path()
    write_wiki_metadata_merge(
        metadata_path,
        {
            "last_compile_time": metadata.last_compile_time.isoformat(),
            "total_concepts": metadata.total_concepts,
            "total_articles": metadata.total_articles,
            "total_raw_files": metadata.total_raw_files,
            "version": metadata.version,
            LAST_COMPILE_RAW_HASHES_KEY: raw_hashes,
        },
    )
    logger.info(f"Saved metadata: {metadata_path}")
