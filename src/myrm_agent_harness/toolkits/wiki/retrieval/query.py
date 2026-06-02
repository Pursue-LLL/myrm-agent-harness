"""Wiki query engine - Query and enhance knowledge base.

[INPUT]
langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
..core.config::WikiConfig, WikiQueryConfig (POS: Wiki configuration center)
..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
..core.types::QueryResult (POS: Wiki toolkit type definition center)

[OUTPUT]
WikiQueryEngine: Wiki query and enhancement engine

[POS]
Wiki query core engine. Responsible for querying the wiki knowledge base and answering questions:
concept search, context loading, LLM answer generation, and automatic archival of high-value results.
Uses semantic search when enable_semantic_search=True and search_fn is injected; falls back to keyword matching otherwise.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..core.config import WikiConfig, WikiQueryConfig
from ..core.structure import WikiStructure
from ..core.types import QueryResult
from .indexer import WikiIndexer

logger = get_agent_logger(__name__)

SemanticSearchFn = Callable[[str, int], Awaitable[list[tuple[Path, float]]]]


class WikiQueryEngine:
    """
    Query engine for LLM-Wiki knowledge base.

    Features:
    - O(1) FTS5 semantic search across wiki articles
    - Context-aware question answering
    - Automatic knowledge enhancement (archive valuable results)
    - Related concept recommendations
    """

    def __init__(
        self,
        llm: BaseChatModel,
        structure: WikiStructure,
        config: WikiConfig,
        query_config: WikiQueryConfig | None = None,
        search_fn: SemanticSearchFn | None = None,
    ):
        self._llm = llm
        self._structure = structure
        self._config = config
        self._query_config = query_config or WikiQueryConfig()
        self._search_fn = search_fn
        self._indexer = WikiIndexer(structure)

    async def query(self, question: str) -> QueryResult:
        """
        Query the wiki and get an answer.

        Args:
            question: User's question

        Returns:
            QueryResult with context and related articles
        """
        logger.info(f"Querying wiki: {question[:100]}")

        # Step 1: Search for related concepts
        related_articles = await self._search_concepts(question)
        logger.info(f"Found {len(related_articles)} related articles")

        if not related_articles:
            return QueryResult(
                question=question,
                answer="No relevant information found in wiki. Consider ingesting more documents.",
                related_articles=[],
                should_archive=False,
                confidence_score=0.0,
            )

        # Step 2: Load article context
        context = await self._load_articles_context(related_articles)

        # Step 3: Determine if should archive
        confidence = 1.0
        should_archive = (
            self._query_config.auto_enhance_enabled and confidence >= self._query_config.min_query_quality_score
        )

        return QueryResult(
            question=question,
            answer=context,
            related_articles=[str(a) for a in related_articles],
            should_archive=should_archive,
            confidence_score=confidence,
        )

    async def _search_concepts(self, query: str) -> list[Path]:
        """Search for relevant concept articles with graph traversal expansion.

        Priority: injected search_fn > FTS5 indexer > keyword fallback.
        Then expands results via 1-hop graph traversal for deeper discovery.
        """
        concepts = self._structure.list_concepts()
        if not concepts:
            return []

        top_n = self._query_config.max_context_articles
        seed_results: list[str] = []

        if self._config.enable_semantic_search:
            if self._search_fn is not None:
                try:
                    results = await self._search_fn(query, top_n)
                    if results:
                        seed_results = [path.stem for path, _score in results[:top_n]]
                except Exception as e:
                    logger.warning(f"Injected search_fn failed: {e}")

            if not seed_results:
                try:
                    results = await self._indexer.search(query, limit=top_n)
                    if results:
                        seed_results = [name for name, _score in results]
                except Exception as e:
                    logger.warning(f"FTS5 semantic search failed: {e}")

        if not seed_results:
            return self._keyword_search(query, concepts, top_n)

        # Graph traversal expansion: discover related concepts via edges
        expanded = self._expand_via_graph(seed_results, top_n)
        return [self._structure.get_concept_file_path(name) for name in expanded]

    def _expand_via_graph(self, seed_names: list[str], max_results: int) -> list[str]:
        """Expand seed results via 1-hop weighted graph traversal."""
        if not seed_names:
            return []

        result_set: list[str] = list(seed_names)
        seen = set(seed_names)

        try:
            with self._indexer._get_conn() as conn:
                placeholders = ",".join(["?"] * len(seed_names))
                cursor = conn.execute(
                    f"SELECT target, weight FROM wiki_edges WHERE source IN ({placeholders}) ORDER BY weight DESC",
                    tuple(seed_names),
                )
                for row in cursor.fetchall():
                    target = row["target"]
                    if target not in seen and len(result_set) < max_results:
                        result_set.append(target)
                        seen.add(target)
        except Exception as e:
            logger.warning(f"Graph expansion failed: {e}")

        return result_set[:max_results]

    def _keyword_search(self, query: str, concepts: list[Path], top_n: int) -> list[Path]:
        """Score concepts by keyword overlap with query."""
        query_keywords = set(re.findall(r"\w+", query.lower()))
        scored: list[tuple[Path, float]] = []

        for concept_path in concepts:
            try:
                content = concept_path.read_text(encoding="utf-8")
                content_keywords = set(re.findall(r"\w+", content.lower()))
                overlap = len(query_keywords & content_keywords)
                score = overlap / max(len(query_keywords), 1)
                if score > 0:
                    scored.append((concept_path, score))
            except Exception as e:
                logger.warning("Failed to read %s: %s", concept_path, e)

        scored.sort(key=lambda x: x[1], reverse=True)
        return [path for path, _ in scored[:top_n]]

    async def _load_articles_context(self, article_paths: list[Path]) -> str:
        """Load article content as context (optimized to only extract Compiled Truth for caching)."""
        context_parts = []

        for path in article_paths:
            try:
                content = path.read_text(encoding="utf-8")

                # Extract only YAML frontmatter and Compiled Truth section to protect prompt caching
                truth_content = ""

                # 1. Extract YAML Frontmatter if present
                yaml_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
                if yaml_match:
                    truth_content += f"---\n{yaml_match.group(1)}\n---\n\n"

                # 2. Extract Compiled Truth section
                truth_match = re.search(r"(## Compiled Truth\n.*?)(?=\n## |$)", content, re.DOTALL)
                if truth_match:
                    truth_content += truth_match.group(1).strip()
                else:
                    # Fallback to full content if the section doesn't exist
                    truth_content = content

                context_parts.append(f"# {path.stem}\n\n{truth_content}")
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")

        return "\n\n---\n\n".join(context_parts)
