"""Post-compilation processing: index, backlinks, and metadata persistence.

[INPUT]
..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
..core.config::WikiConfig (POS: Wiki configuration center)
..core.types::ConceptInfo, WikiMetadata (POS: Wiki toolkit type definitions)

[OUTPUT]
build_index(): Build the wiki index file
generate_backlinks(): Generate Obsidian-compatible backlinks between concepts
save_metadata(): Persist compilation metadata with SHA256 file hashes

[POS]
Post-compilation steps: index generation, backlink creation, and metadata persistence
after concept extraction and article generation are complete.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..core.structure import WikiStructure
from ..core.types import ConceptInfo, WikiMetadata

if TYPE_CHECKING:
    from ..core.config import WikiConfig
    from ..retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)

_RELATED_SECTION_RE: re.Pattern[str] = re.compile(r"\n+## Related Concepts\n.*", re.DOTALL)


async def build_index(structure: WikiStructure, concepts: list[ConceptInfo]) -> None:
    """Build main wiki index file."""
    index_content = "# Wiki Index\n\n"
    index_content += f"*Last updated: {datetime.now(UTC).isoformat()}*\n\n"
    index_content += "## Concepts\n\n"

    for concept in sorted(concepts, key=lambda c: c.name):
        index_content += f"- [[{concept.name}]]\n"

    index_path = structure.get_index_file_path()
    index_path.write_text(index_content, encoding="utf-8")
    logger.info(f"Built index: {index_path}")


async def generate_backlinks(
    structure: WikiStructure,
    config: "WikiConfig",
    concepts: list[ConceptInfo],
    indexer: "WikiIndexer | None" = None,
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
                indexer.extract_and_upsert_edges(concept.name, content)
            else:
                from ..retrieval.indexer import WikiIndexer as _WikiIndexer

                _idx = _WikiIndexer(structure, config)
                _idx.extract_and_upsert_edges(concept.name, content)

        except Exception as e:
            logger.error(f"Failed to add backlinks for {concept.name}: {e}")

    return backlinks_count


async def save_metadata(
    structure: WikiStructure,
    concepts_count: int,
    articles_count: int,
) -> None:
    """Save wiki metadata including SHA256 file hashes for incremental compilation."""
    raw_files = structure.list_raw_files()
    file_hashes: dict[str, str] = {}
    for f in raw_files:
        with contextlib.suppress(OSError):
            file_hashes[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()

    metadata = WikiMetadata(
        last_compile_time=datetime.now(UTC),
        total_concepts=concepts_count,
        total_articles=articles_count,
        total_raw_files=len(raw_files),
    )

    metadata_path = structure.get_wiki_metadata_path()
    metadata_dict = {
        "last_compile_time": metadata.last_compile_time.isoformat(),
        "total_concepts": metadata.total_concepts,
        "total_articles": metadata.total_articles,
        "total_raw_files": metadata.total_raw_files,
        "version": metadata.version,
        "file_hashes": file_hashes,
    }

    metadata_path.write_text(json.dumps(metadata_dict, indent=2), encoding="utf-8")
    logger.info(f"Saved metadata: {metadata_path}")
