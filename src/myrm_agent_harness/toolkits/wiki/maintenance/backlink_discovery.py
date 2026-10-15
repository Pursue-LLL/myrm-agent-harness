"""LLM-driven wikilink enrichment for wiki articles.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
- ..core.claims_contract::read_wiki_metadata_file, write_wiki_metadata_merge (POS: wiki `.metadata.json` access; holds the rotation cursor)
- ..core.frontmatter_contract::resolve_publish_status (POS: publish_status SSOT; only published pages take part)
- ..core.link_extraction::extract_wikilink_targets (POS: link syntax SSOT; pages already linked from an article)
- ..core.link_resolver::WikiLinkResolver, concept_link_name (POS: link target to page identity, vault-relative page name)
- ..core.related_links::merge_related_links (POS: the only writer of a page's Related Concepts section)
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- .progress::MaintainPhase, MaintainProgressCallback, report_progress (POS: observer of how far the LLM phases are)
- ..pipeline.publication::publish_concept_article (POS: single validated write + index path for concept articles)
- ..retrieval.indexer::WikiIndexer (POS: wiki FTS5 + vector index and graph edges)
- utils.chat_utils::extract_answer_text (POS: LLM 响应答案提取)
- utils.json_parsing::parse_llm_json_list (POS: robust JSON array extraction from LLM output)
- utils.markdown_frontmatter::parse_frontmatter (POS: article body without its frontmatter)

[OUTPUT]
- LINK_DISCOVERY_CURSOR_KEY: `.metadata.json` key of the rotation cursor
- BacklinkDiscoveryMixin: `_discover_connections` for WikiLinter, which adds LLM-suggested wikilinks to articles

[POS]
Wiki cross-reference discovery. Asks the LLM which existing concepts an article should link to and
adds the valid, not yet linked ones to its Related Concepts section, keeping LLM link enrichment apart
from WikiLinter's health checks. Every run asks about the next batch of published local articles,
so the whole vault is covered over successive runs; drafts, blocked pages, templates and mounted
public wikis are neither rewritten nor offered as link targets.
"""

from __future__ import annotations

import bisect
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
    read_wiki_metadata_file,
    write_wiki_metadata_merge,
)
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import WikiPublishStatus, resolve_publish_status
from myrm_agent_harness.toolkits.wiki.core.link_extraction import extract_wikilink_targets
from myrm_agent_harness.toolkits.wiki.core.link_resolver import WikiLinkResolver, concept_link_name
from myrm_agent_harness.toolkits.wiki.core.related_links import merge_related_links
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.maintenance.progress import (
    MaintainPhase,
    MaintainProgressCallback,
    report_progress,
)
from myrm_agent_harness.toolkits.wiki.pipeline.publication import (
    ArticlePublishOutcome,
    publish_concept_article,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.json_parsing import parse_llm_json_list
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)

LINK_DISCOVERY_CURSOR_KEY = "link_discovery_cursor"

_BATCH_SIZE = 20
_EXCERPT_CHARS = 1500

_SYSTEM_PROMPT = (
    "You are a knowledge graph expert. Given a wiki article and a list of other concepts, "
    "identify which concepts should be linked FROM this article using [[Wikilinks]]. "
    "Only suggest links where there's a genuine semantic relationship. "
    'Return ONLY a JSON array of concept names to link, e.g. ["Concept A", "Concept B"]. '
    "Return [] if no links are needed."
)


def _discovery_pages(structure: WikiStructure) -> dict[str, Path]:
    """Published local article pages by vault-relative key, in key order.

    Drafts and blocked pages wait for a person's decision, templates are not articles and
    mounted public wikis are read-only: none of them is rewritten or offered as a link target.
    """
    pages: dict[str, Path] = {}
    for path in structure.list_concepts():
        if not path.is_relative_to(structure.concepts_dir) or path.is_relative_to(structure.templates_dir):
            continue
        try:
            status = resolve_publish_status(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if status is WikiPublishStatus.PUBLISHED:
            pages[concept_link_name(path, structure.concepts_dir)] = path
    return dict(sorted(pages.items()))


def _publishes_in_place(structure: WikiStructure, key: str, path: Path) -> bool:
    """Whether publishing ``key`` rewrites ``path`` itself.

    Publishing writes to the sanitized file name. A hand-made page whose name differs from that
    (``Alpha Notes.md``) would be left untouched and gain a sibling copy instead; on a
    case-insensitive file system a name that differs only in case is still the same file.
    The path is only computed, never created: looking must not add folders to the vault.
    """
    target = structure.concepts_dir / f"{WikiStructure._sanitize_path(key)}.md"
    return target == path or (target.exists() and target.samefile(path))


def _next_batch(keys: list[str], cursor: object) -> list[str]:
    """The next ``_BATCH_SIZE`` keys after ``cursor``, wrapping around the end of the vault."""
    start = bisect.bisect_right(keys, cursor) if isinstance(cursor, str) else 0
    return (keys[start:] + keys[:start])[:_BATCH_SIZE]


def _excerpt(content: str) -> str:
    """The start of the article body: frontmatter says nothing about what the page should link to."""
    _metadata, body = parse_frontmatter(content)
    return body.strip()[:_EXCERPT_CHARS]


def _new_link_targets(
    content: str,
    key: str,
    suggested: list[object],
    pages: dict[str, Path],
    resolver: WikiLinkResolver,
) -> list[str]:
    """Pages the model suggested that exist, are not the article itself and are not linked yet."""
    linked = {resolver.resolve(target, key) for target in extract_wikilink_targets(content)}
    accepted: dict[str, None] = {}
    for name in suggested:
        if not isinstance(name, str):
            continue
        target = resolver.resolve(name, key)
        if target is not None and target != key and target in pages and target not in linked:
            accepted[target] = None
    return list(accepted)


class BacklinkDiscoveryMixin:
    """LLM backlink discovery for WikiLinter.

    Expects the host class to provide: _llm, _structure, _indexer.
    """

    _llm: BaseChatModel
    _structure: WikiStructure
    _indexer: WikiIndexer | None

    async def _discover_connections(self, on_progress: MaintainProgressCallback | None = None) -> int:
        """
        Discover potential cross-references using LLM-driven link enrichment.

        Uses LLM to identify semantic relationships that simple string matching would miss,
        while avoiding false positives from naive keyword overlap. Asks about one batch of
        articles per run and continues after the last one asked about on the next run.

        Args:
            on_progress: told how many pages of the batch are done, before each page and once at the end.

        Returns:
            Number of new connections discovered
        """
        pages = _discovery_pages(self._structure)
        if len(pages) < 2:
            return 0

        metadata_path = self._structure.get_wiki_metadata_path()
        keys = list(pages)
        batch = _next_batch(keys, read_wiki_metadata_file(metadata_path).get(LINK_DISCOVERY_CURSOR_KEY))
        candidates = "\n".join(f"- {key}" for key in keys)
        resolver = WikiLinkResolver(self._structure)

        connections_count = 0
        unanswered = 0
        for done, key in enumerate(batch):
            report_progress(on_progress, MaintainPhase.LINK_DISCOVERY, done, len(batch))
            try:
                suggested = await self._suggest_links(key, pages, candidates, resolver)
            except Exception as e:
                unanswered += 1
                logger.warning(f"LLM link suggestion failed for {key}: {e}")
                continue
            try:
                connections_count += await self._add_links(key, suggested, pages, resolver)
            except Exception as e:
                logger.warning(f"Adding suggested links to {key} failed: {e}")
        report_progress(on_progress, MaintainPhase.LINK_DISCOVERY, len(batch), len(batch))

        # A batch the model answered for no page is an outage: ask the same pages again next run.
        # A page that cannot take a link (invalid frontmatter, say) fails the same way every run and
        # must not hold the rotation back.
        if len(keys) > _BATCH_SIZE and unanswered < len(batch):
            try:
                write_wiki_metadata_merge(metadata_path, {LINK_DISCOVERY_CURSOR_KEY: batch[-1]})
            except OSError as e:
                logger.warning(f"Link discovery cursor not saved, the next run asks about the same pages again: {e}")
        return connections_count

    async def _suggest_links(
        self,
        key: str,
        pages: dict[str, Path],
        candidates: str,
        resolver: WikiLinkResolver,
    ) -> list[object]:
        """Ask the model which pages one article should link to; raises when it could not be asked."""
        path = pages[key]
        if not _publishes_in_place(self._structure, key, path):
            logger.warning(f"Skipping link enrichment for {key}: publishing would write a different file than {path}")
            return []
        content = path.read_text(encoding="utf-8")
        linked = sorted({resolver.resolve(t, key) or t for t in extract_wikilink_targets(content)})

        response = await self._llm.ainvoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"## Article: {key}\n{_excerpt(content)}\n\n"
                        f"## Available concepts to potentially link:\n{candidates}\n\n"
                        f"## Already linked: {linked}"
                    )
                ),
            ]
        )
        return parse_llm_json_list(extract_answer_text(response).strip()) or []

    async def _add_links(
        self,
        key: str,
        suggested: list[object],
        pages: dict[str, Path],
        resolver: WikiLinkResolver,
    ) -> int:
        """Add the valid, not yet linked suggestions to the article; returns how many were added."""
        if not suggested:
            return 0
        # The model call took seconds: merge into the page as it is now, with nothing awaited before the write.
        path = pages[key]
        content = path.read_text(encoding="utf-8")
        targets = _new_link_targets(content, key, suggested, pages, resolver)
        merged, added = merge_related_links(content, targets, source=key, resolver=resolver)
        if not added:
            return 0
        outcome = await publish_concept_article(self._structure, self._indexer, key, merged)
        if outcome is not ArticlePublishOutcome.PUBLISHED:
            return 0
        logger.info(f"LLM discovered {added} link(s) from {key}: {', '.join(targets)}")
        return added
