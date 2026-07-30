"""Backlink helper when evolution synthesis pages are approved.

[INPUT]
..pipeline.publication.publish_concept_article (POS: publish updated concept pages)
..core.section_contract (POS: append Timeline entries)

[OUTPUT]
- apply_synthesis_backlinks: append timeline links on linked concept pages

[POS]
Post-approve hook so published evolution pages are discoverable from both sides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    load_frontmatter_metadata,
    serialize_frontmatter_block,
)
from myrm_agent_harness.toolkits.wiki.core.section_contract import TIMELINE_HEADING, append_section_entry
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .writer import parse_synthesis_backlink_targets, synthesis_page_uses_cjk_body

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)


async def apply_synthesis_backlinks(
    structure: WikiStructure,
    indexer: WikiIndexer | None,
    *,
    synthesis_concept_name: str,
    synthesis_content: str,
) -> int:
    """Append timeline backlinks on linked concepts. Returns number of pages updated."""
    linked = parse_synthesis_backlink_targets(synthesis_content)
    if not linked:
        return 0

    from myrm_agent_harness.toolkits.wiki.pipeline.publication import publish_concept_article

    updated = 0
    if synthesis_page_uses_cjk_body(synthesis_content):
        entry = f"冲突合成已发布：[[{synthesis_concept_name}]]"
    else:
        entry = f"Conflict synthesis published: [[{synthesis_concept_name}]]"
    for concept_name in linked:
        path = structure.get_concept_file_path(concept_name)
        if not path.exists():
            continue
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            continue
        metadata, body = load_frontmatter_metadata(existing)
        try:
            new_body, appended = append_section_entry(body, TIMELINE_HEADING, entry)
        except ValueError as exc:
            logger.warning("Skipping synthesis backlink for %s: %s", concept_name, exc)
            continue
        if not appended:
            continue
        new_content = serialize_frontmatter_block(metadata) + new_body.lstrip("\n")
        await publish_concept_article(structure, indexer, concept_name, new_content)
        updated += 1
    return updated
