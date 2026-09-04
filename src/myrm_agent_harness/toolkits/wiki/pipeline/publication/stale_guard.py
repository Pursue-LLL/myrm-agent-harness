"""Stale-source guard for HITL pending edits.

[INPUT]
- ..core.frontmatter_contract::ensure_draft_frontmatter (POS: publish_status draft stamp)
- ..core.structure::WikiStructure (POS: vault paths)
- ..retrieval.indexer::WikiIndexer (POS: FTS reindex on demote)

[OUTPUT]
- sources_newer_than_article, demote_stale_published_article, StalePendingApprovalError

[POS]
When compile stages a new pending draft, demote stale published articles from RAG.
Block approve when raw sources are newer than the on-disk article.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    PUBLISH_STATUS_KEY,
    WikiPublishStatus,
    ensure_draft_frontmatter,
)
from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = logging.getLogger(__name__)


class StalePendingApprovalError(ValueError):
    """Raised when a pending draft is approved while linked raw sources are newer."""


def _sources_from_content(content: str) -> list[str]:
    metadata, _body = parse_frontmatter(content)
    raw_sources = metadata.get("sources")
    if raw_sources is None:
        return []
    if isinstance(raw_sources, list):
        return [str(item).strip() for item in raw_sources if str(item).strip()]
    source_str = str(raw_sources).strip()
    return [source_str] if source_str else []


def _resolve_raw_path(structure: WikiStructure, source_ref: str) -> Path | None:
    ref = source_ref.strip().replace("\\", "/")
    if not ref:
        return None

    candidate = Path(ref)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    raw_path = structure.get_raw_file_path(ref)
    if raw_path.exists():
        return raw_path

    if ref.startswith("raw/"):
        trimmed = ref.removeprefix("raw/")
        raw_path = structure.get_raw_file_path(trimmed)
        if raw_path.exists():
            return raw_path

    return None


def sources_newer_than_article(
    structure: WikiStructure,
    concept_name: str,
    proposed_content: str,
    *,
    source_files: list[str] | None = None,
) -> bool:
    """Return True when any linked raw source is newer than the on-disk concept article."""
    article_path = structure.get_concept_file_path(concept_name)
    if not article_path.exists():
        return False

    try:
        article_mtime = article_path.stat().st_mtime
    except OSError:
        return False

    sources = source_files if source_files else _sources_from_content(proposed_content)
    if not sources:
        return False

    for source_ref in sources:
        raw_path = _resolve_raw_path(structure, source_ref)
        if raw_path is None:
            continue
        try:
            if raw_path.stat().st_mtime > article_mtime:
                return True
        except OSError:
            continue
    return False


async def demote_stale_published_article(
    structure: WikiStructure,
    indexer: WikiIndexer | None,
    concept_name: str,
) -> bool:
    """Demote an on-disk published concept to draft and refresh the search index."""
    article_path = structure.get_concept_file_path(concept_name)
    if not article_path.exists():
        return False

    try:
        content = article_path.read_text(encoding="utf-8")
    except OSError:
        return False

    metadata, _body = parse_frontmatter(content)
    status = str(metadata.get(PUBLISH_STATUS_KEY, "")).strip().lower()
    if status == WikiPublishStatus.DRAFT.value:
        return False

    draft_content = ensure_draft_frontmatter(content)
    article_path.write_text(draft_content, encoding="utf-8")

    if indexer is None:
        from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

        indexer = WikiIndexer(structure)

    await indexer.upsert(concept_name, draft_content)
    edge_result = indexer.extract_and_upsert_edges(concept_name, draft_content)
    if hasattr(edge_result, "__await__"):
        await edge_result

    logger.info("Demoted stale published wiki concept to draft: %s", concept_name)
    return True
