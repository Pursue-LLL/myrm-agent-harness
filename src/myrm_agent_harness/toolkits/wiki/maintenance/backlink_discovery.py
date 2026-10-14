"""LLM-driven wikilink enrichment for wiki articles.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
- ..core.link_extraction::extract_wikilink_targets (POS: link syntax SSOT; pages already linked from an article)
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- ..pipeline.publication::publish_concept_article (POS: single validated write + index path for concept articles)
- ..retrieval.indexer::WikiIndexer (POS: wiki FTS5 + vector index and graph edges)
- utils.chat_utils::extract_answer_text (POS: LLM 响应答案提取)
- utils.json_parsing::parse_llm_json_list (POS: robust JSON array extraction from LLM output)

[OUTPUT]
- BacklinkDiscoveryMixin: `_discover_connections` for WikiLinter, which appends LLM-suggested wikilinks to articles

[POS]
Wiki cross-reference discovery. Asks the LLM which existing concepts an article should link to and
appends the valid, not yet linked ones, keeping LLM link enrichment apart from WikiLinter's health checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.wiki.core.link_extraction import extract_wikilink_targets
from myrm_agent_harness.toolkits.wiki.pipeline.publication import (
    publish_concept_article,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.json_parsing import parse_llm_json_list
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)


class BacklinkDiscoveryMixin:
    """LLM backlink discovery for WikiLinter.

    Expects the host class to provide: _llm, _structure, _indexer.
    """

    _llm: BaseChatModel
    _structure: WikiStructure
    _indexer: WikiIndexer | None

    async def _discover_connections(self) -> int:
        """
        Discover potential cross-references using LLM-driven link enrichment.

        Uses LLM to identify semantic relationships that simple string matching would miss,
        while avoiding false positives from naive keyword overlap.

        Returns:
            Number of new connections discovered
        """
        concepts = self._structure.list_concepts()
        if len(concepts) < 2:
            return 0

        connections_count = 0
        concept_names = [p.stem.replace("-", " ") for p in concepts]
        concept_index = "\n".join(f"- {name}" for name in concept_names)

        for concept_path in concepts[:20]:
            try:
                content = concept_path.read_text(encoding="utf-8")
                current_name = concept_path.stem.replace("-", " ")

                # Extract existing wikilinks to avoid duplicates
                existing_links = extract_wikilink_targets(content)
                existing_links_lower = {link.lower() for link in existing_links}

                system_msg = SystemMessage(
                    content=(
                        "You are a knowledge graph expert. Given a wiki article and a list of other concepts, "
                        "identify which concepts should be linked FROM this article using [[Wikilinks]]. "
                        "Only suggest links where there's a genuine semantic relationship. "
                        'Return ONLY a JSON array of concept names to link, e.g. ["Concept A", "Concept B"]. '
                        "Return [] if no links are needed."
                    )
                )
                human_msg = HumanMessage(
                    content=(
                        f"## Article: {current_name}\n{content[:1500]}\n\n"
                        f"## Available concepts to potentially link:\n{concept_index}\n\n"
                        f"## Already linked: {list(existing_links)}"
                    )
                )

                response = await self._llm.ainvoke([system_msg, human_msg])
                response_text = extract_answer_text(response).strip()

                try:
                    suggested = parse_llm_json_list(response_text)
                    if suggested is None:
                        continue
                except (TypeError, ValueError):
                    continue

                # Add new wikilinks
                article_modified = False
                for link_name in suggested:
                    if not isinstance(link_name, str):
                        continue
                    if link_name.lower() in existing_links_lower or link_name.lower() == current_name.lower():
                        continue
                    # Verify concept exists
                    if link_name.lower() not in {n.lower() for n in concept_names}:
                        continue

                    content += f"\n- [[{link_name}]]"
                    article_modified = True
                    connections_count += 1
                    logger.info(f"LLM discovered link: {current_name} -> {link_name}")

                if article_modified:
                    rel = str(concept_path.relative_to(self._structure.concepts_dir).with_suffix("")).replace("\\", "/")
                    await publish_concept_article(self._structure, self._indexer, rel, content)

            except Exception as e:
                logger.warning(f"LLM link enrichment failed for {concept_path}: {e}")

        return connections_count
