"""Post-compilation processing: index, backlinks, and metadata persistence.

[INPUT]
..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
..core.config::WikiConfig (POS: Wiki configuration center)
..core.types::ConceptInfo, WikiMetadata (POS: Wiki toolkit type definitions)
..core.claims_contract (POS: raw hash metadata keys and collectors)

[OUTPUT]
generate_backlinks(): Generate Obsidian-compatible backlinks between concepts
save_metadata(): Persist compilation metadata with portable SHA256 raw snapshots (preserves raw_supersede lineage)

[POS]
Post-compilation steps: backlink creation and metadata persistence after concept
extraction and article generation. OKF index/log/hot live in cognitive_map/.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..core.claims_contract import (
    LAST_COMPILE_RAW_HASHES_KEY,
    RAW_SUPERSEDE_KEY,
    collect_raw_content_hashes,
    read_wiki_metadata_file,
)
from ..core.structure import WikiStructure
from ..core.types import ConceptInfo, WikiMetadata

if TYPE_CHECKING:
    from ..core.config import WikiConfig
    from ..retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)

_RELATED_SECTION_RE: re.Pattern[str] = re.compile(r"\n+## Related Concepts\n.*", re.DOTALL)


async def generate_backlinks(
    structure: WikiStructure,
    config: WikiConfig,
    concepts: list[ConceptInfo],
    indexer: WikiIndexer | None = None,
) -> int:
    """Generate backlinks between related concepts (Obsidian format).

    Idempotent: replaces existing Related Concepts section if present.
    """
    backlinks_count = 0

    for concept in concepts:
        if not concept.related_concepts:
            continue

        article_path = structure.get_concept_file_path(concept.name)
        if not article_path.exists():
            continue

        try:
            content = article_path.read_text(encoding="utf-8")

            backlinks_section = "\n\n## Related Concepts\n\n"
            for related in concept.related_concepts:
                backlinks_section += f"- [[{related}]]\n"
                backlinks_count += 1

            content = _RELATED_SECTION_RE.sub("", content)
            content += backlinks_section
            article_path.write_text(content, encoding="utf-8")

            if indexer:
                edge_result = indexer.extract_and_upsert_edges(concept.name, content)
                if inspect.isawaitable(edge_result):
                    await edge_result
            else:
                from ..retrieval.indexer import WikiIndexer as _WikiIndexer

                _idx = _WikiIndexer(structure, config)
                edge_result = _idx.extract_and_upsert_edges(concept.name, content)
                if inspect.isawaitable(edge_result):
                    await edge_result

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
    existing = read_wiki_metadata_file(metadata_path)
    preserved_supersede = existing.get(RAW_SUPERSEDE_KEY)
    if not isinstance(preserved_supersede, dict):
        preserved_supersede = {}

    metadata_dict: dict[str, object] = {
        "last_compile_time": metadata.last_compile_time.isoformat(),
        "total_concepts": metadata.total_concepts,
        "total_articles": metadata.total_articles,
        "total_raw_files": metadata.total_raw_files,
        "version": metadata.version,
        LAST_COMPILE_RAW_HASHES_KEY: raw_hashes,
        RAW_SUPERSEDE_KEY: preserved_supersede,
    }

    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata_dict, indent=2), encoding="utf-8")
    logger.info(f"Saved metadata: {metadata_path}")
