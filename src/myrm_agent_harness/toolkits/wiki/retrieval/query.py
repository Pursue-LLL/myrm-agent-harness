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
Uses sidecar-first hierarchical routing with context-budgeted loading (L0/L1 before L2),
and falls back to keyword matching when semantic retrieval is unavailable.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..core.config import WikiConfig, WikiQueryConfig
from ..core.structure import WikiStructure
from ..core.types import QueryResult, SourceSnippet
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
        self._indexer = WikiIndexer(structure, config)

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

        # Step 2: Load article context and extract citation snippets
        context, snippets = await self._load_articles_context(related_articles)

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
            source_snippets=snippets,
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

        if self._query_config.sidecar_retrieval_enabled:
            routed = await self._search_concepts_via_sidecars(query, concepts, top_n=top_n)
            if routed:
                return routed

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

    async def _search_concepts_via_sidecars(
        self,
        query: str,
        concepts: list[Path],
        *,
        top_n: int,
    ) -> list[Path]:
        """Use L0/L1 sidecars to route retrieval into high-value directories first."""
        limit = max(top_n * 3, 8)
        try:
            sidecar_hits = await self._indexer.search_sidecars(query, limit=limit)
        except Exception as e:
            logger.warning("Sidecar retrieval failed: %s", e)
            return []
        if not sidecar_hits:
            return []

        max_dirs = max(0, self._query_config.max_sidecar_directories)
        if max_dirs == 0:
            return []
        ordered_dirs: list[str] = []
        seen_dirs: set[str] = set()
        for dir_path, _level, _score in sidecar_hits:
            if dir_path in seen_dirs:
                continue
            seen_dirs.add(dir_path)
            ordered_dirs.append(dir_path)
            if len(ordered_dirs) >= max_dirs:
                break
        if not ordered_dirs:
            return []

        candidates = self._collect_concepts_from_directory_scopes(ordered_dirs, concepts)
        if not candidates:
            return []

        candidate_name_to_path = {
            self._concept_name_from_path(path): path
            for path in candidates
        }
        ranked_names: list[str] = []
        try:
            indexed_hits = await self._indexer.search(query, limit=max(top_n * 6, 20))
            for concept_name, _score in indexed_hits:
                if concept_name in candidate_name_to_path and concept_name not in ranked_names:
                    ranked_names.append(concept_name)
                if len(ranked_names) >= top_n:
                    break
        except Exception as e:
            logger.warning("Concept rerank after sidecar routing failed: %s", e)

        if len(ranked_names) < top_n:
            for path in self._keyword_search(query, candidates, top_n):
                concept_name = self._concept_name_from_path(path)
                if concept_name not in ranked_names:
                    ranked_names.append(concept_name)
                if len(ranked_names) >= top_n:
                    break

        if ranked_names:
            return [candidate_name_to_path[name] for name in ranked_names if name in candidate_name_to_path]
        return candidates[:top_n]

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

    async def _load_articles_context(self, article_paths: list[Path]) -> tuple[str, list[SourceSnippet]]:
        """Load article content as context and extract citation snippets.

        Returns:
            Tuple of (context_string, list_of_source_snippets).
        """
        context_parts: list[str] = []
        snippets: list[SourceSnippet] = []
        remaining_chars = max(500, self._query_config.max_context_chars)

        # Step 1: directory-level L0/L1 context
        if self._query_config.sidecar_retrieval_enabled:
            sidecar_parts, sidecar_chars, sidecar_snippets = self._load_directory_sidecars(article_paths)
            if sidecar_parts:
                context_parts.extend(sidecar_parts)
                remaining_chars = max(0, remaining_chars - sidecar_chars)
            if sidecar_snippets:
                snippets.extend(sidecar_snippets)

        # Step 2: full article context (L2), bounded by count and hard char budget
        max_full_articles = max(1, min(len(article_paths), self._query_config.max_full_articles))
        loaded_articles = 0
        for path in article_paths:
            if loaded_articles >= max_full_articles or remaining_chars <= 0:
                break
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
                    truth_content = content

                block = f"# {path.stem}\n\n{truth_content}".strip()
                if len(block) > remaining_chars:
                    clipped = block[:remaining_chars].rsplit(" ", 1)[0].strip()
                    if not clipped:
                        break
                    block = f"{clipped}\n\n[... truncated by context budget]"
                context_parts.append(block)
                remaining_chars -= len(block)
                loaded_articles += 1

                # 3. Extract snippet: first meaningful section or paragraph (≤500 chars)
                snippet_text, section_name = self._extract_snippet(truth_content)
                snippets.append(
                    SourceSnippet(
                        article_path=str(path),
                        article_name=path.stem,
                        snippet=snippet_text,
                        section=section_name,
                        level="L2",
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")

        return "\n\n---\n\n".join(context_parts), snippets

    def _load_directory_sidecars(self, article_paths: list[Path]) -> tuple[list[str], int, list[SourceSnippet]]:
        parts: list[str] = []
        total_chars = 0
        snippets: list[SourceSnippet] = []
        seen: set[str] = set()
        max_dirs = max(0, self._query_config.max_sidecar_directories)
        if max_dirs == 0:
            return parts, total_chars, snippets
        for article in article_paths:
            try:
                rel = article.relative_to(self._structure.concepts_dir).with_suffix("")
            except ValueError:
                continue
            dir_path = "" if str(rel.parent) in (".", "") else str(rel.parent).replace("\\", "/")
            if dir_path in seen:
                continue
            seen.add(dir_path)
            if len(seen) > max_dirs:
                break
            abstract = self._indexer.get_sidecar_truth(dir_path, level=0)
            overview = self._indexer.get_sidecar_truth(dir_path, level=1)
            if abstract:
                block = f"# Directory {dir_path or '/'} (L0)\n\n{abstract.strip()}"
                parts.append(block)
                total_chars += len(block)
                abstract_snippet, abstract_section = self._extract_snippet(abstract, max_chars=300)
                snippets.append(
                    SourceSnippet(
                        article_path=self._sidecar_source_path(dir_path, level="L0"),
                        article_name=dir_path or "/",
                        snippet=abstract_snippet or abstract.strip()[:300],
                        section=abstract_section or "Directory Abstract",
                        level="L0",
                    )
                )
            if overview:
                block = f"# Directory {dir_path or '/'} (L1)\n\n{overview.strip()}"
                parts.append(block)
                total_chars += len(block)
                overview_snippet, overview_section = self._extract_snippet(overview, max_chars=300)
                snippets.append(
                    SourceSnippet(
                        article_path=self._sidecar_source_path(dir_path, level="L1"),
                        article_name=dir_path or "/",
                        snippet=overview_snippet or overview.strip()[:300],
                        section=overview_section or "Directory Overview",
                        level="L1",
                    )
                )
        return parts, total_chars, snippets

    def _collect_concepts_from_directory_scopes(
        self,
        dir_paths: list[str],
        concepts: list[Path],
    ) -> list[Path]:
        ordered: list[Path] = []
        seen_paths: set[Path] = set()

        for dir_path in dir_paths:
            normalized = dir_path.strip("/").replace("\\", "/")
            for concept in concepts:
                try:
                    rel = concept.relative_to(self._structure.concepts_dir).with_suffix("")
                except ValueError:
                    continue
                concept_name = str(rel).replace("\\", "/")
                if normalized and not concept_name.startswith(f"{normalized}/"):
                    continue
                if concept not in seen_paths:
                    seen_paths.add(concept)
                    ordered.append(concept)
        return ordered

    def _concept_name_from_path(self, path: Path) -> str:
        rel = path.relative_to(self._structure.concepts_dir).with_suffix("")
        return str(rel).replace("\\", "/")

    @staticmethod
    def _sidecar_source_path(dir_path: str, *, level: str) -> str:
        filename = (
            WikiStructure.DIRECTORY_ABSTRACT_FILENAME if level == "L0" else WikiStructure.DIRECTORY_OVERVIEW_FILENAME
        )
        normalized = dir_path.strip("/")
        if not normalized:
            return f"/{filename}"
        return f"{normalized}/{filename}"

    @staticmethod
    def _extract_snippet(content: str, max_chars: int = 500) -> tuple[str, str]:
        """Extract the first meaningful paragraph as a citation snippet.

        Returns:
            Tuple of (snippet_text, section_heading).
        """
        section_name = ""

        # Strip YAML frontmatter
        stripped = re.sub(r"^---\n.*?\n---\n*", "", content, count=1, flags=re.DOTALL)

        # Find the first section heading (## ...)
        section_match = re.search(r"^(#{1,3})\s+(.+)$", stripped, re.MULTILINE)
        if section_match:
            section_name = section_match.group(2).strip()

        # Collect non-empty, non-heading lines as the snippet
        lines: list[str] = []
        total = 0
        for line in stripped.split("\n"):
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                if lines:
                    break
                continue
            lines.append(line_stripped)
            total += len(line_stripped)
            if total >= max_chars:
                break

        snippet = " ".join(lines)
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rsplit(" ", 1)[0] + "…"

        return snippet, section_name
