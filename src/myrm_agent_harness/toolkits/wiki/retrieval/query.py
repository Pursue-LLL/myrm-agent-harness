"""Wiki query engine - Query and enhance knowledge base.

[INPUT]
langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
..core.config::WikiConfig, WikiQueryConfig (POS: Wiki configuration center)
..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
..core.types::QueryResult (POS: Wiki toolkit type definition center)
..pipeline.cognitive_map::read_hot_context, read_log_context (POS: OKF hot.md / log.md readers for wiki_query prefix)
..pipeline.cognitive_map.index_routing::format_index_route_context, match_index_entries, read_index_entries (POS: OKF index-first routing)
.best_first::RetrievalSeed, converge_retrieval_candidates (POS: budgeted best-first graph convergence + raw_claim rerank)

[OUTPUT]
WikiQueryEngine: Wiki query and enhancement engine; derived QueryResult.confidence_score; QueryResult.retrieval_trace metadata

[POS]
Wiki query core engine. Responsible for querying the wiki knowledge base and answering questions:
concept search, context loading, LLM answer generation, and automatic archival of high-value results.
Uses index-first seeding, then sidecar hierarchical routing, FTS rerank, and best-first graph
convergence with context-budgeted loading (L0/L1 before L2). Prepends hot.md vault status inside
wiki_query answers only (no global agent middleware), and falls back to keyword matching when
semantic retrieval is unavailable. Supports raw_claim rerank, claim-health multipliers, and
derived confidence for citation scoring.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..core.config import WikiConfig, WikiQueryConfig
from ..core.structure import WikiStructure
from ..core.types import (
    QueryResult,
    SourceSnippet,
    WikiIndexTraceHit,
    WikiRetrievalSeedTrace,
    WikiRetrievalTrace,
)
from ..pipeline.cognitive_map import read_hot_context, read_log_context
from ..pipeline.cognitive_map.index_routing import (
    INDEX_ROUTING_SECTION,
    IndexRouteEntry,
    format_index_route_context,
    match_index_entries,
    read_index_entries,
)
from .asset_index import WikiAssetIndexer
from .best_first import RetrievalSeed, converge_retrieval_candidates
from .indexer import WikiIndexer
from .tokenizer import extract_query_terms

logger = get_agent_logger(__name__)

SemanticSearchFn = Callable[[str, int], Awaitable[list[tuple[Path, float]]]]


@dataclass(frozen=True, slots=True)
class _ConceptSearchResult:
    article_paths: list[Path]
    index_matches: list[tuple[IndexRouteEntry, float]]
    seeds: list[RetrievalSeed]
    sidecar_directories: list[str]


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
        self._asset_indexer: WikiAssetIndexer | None = None

    async def query(
        self,
        question: str,
        query_config: WikiQueryConfig | None = None,
    ) -> QueryResult:
        """
        Query the wiki and get an answer.

        Args:
            question: User's question
            query_config: Optional per-query config override (e.g. raw_claim mode)

        Returns:
            QueryResult with context and related articles
        """
        effective_query_config = query_config or self._query_config
        logger.info(f"Querying wiki: {question[:100]}")

        hot_context = read_hot_context(self._structure)
        log_context = read_log_context(self._structure)

        # Step 1: Search for related concepts
        search_result = await self._search_concepts(question, effective_query_config)
        related_articles = search_result.article_paths
        logger.info(f"Found {len(related_articles)} related articles")

        if not related_articles:
            asset_snippets = await self._search_asset_snippets(question)
            if asset_snippets:
                asset_lines = "\n".join(
                    f"- {snippet.snippet} ({snippet.article_path})" for snippet in asset_snippets
                )
                answer = self._compose_answer(
                    hot_context,
                    log_context,
                    f"## Related images\n{asset_lines}",
                    question,
                )
                return QueryResult(
                    question=question,
                    answer=answer,
                    related_articles=[],
                    should_archive=False,
                    confidence_score=0.5,
                    source_snippets=asset_snippets,
                )
            if hot_context or log_context:
                return QueryResult(
                    question=question,
                    answer=self._compose_hot_only_answer(hot_context, log_context),
                    related_articles=[],
                    should_archive=False,
                    confidence_score=0.1,
                )
            return QueryResult(
                question=question,
                answer="No relevant information found in wiki. Consider ingesting more documents.",
                related_articles=[],
                should_archive=False,
                confidence_score=0.0,
            )

        # Step 2: Load article context and extract citation snippets
        context, snippets = await self._load_articles_context(
            related_articles,
            search_result.index_matches,
            effective_query_config,
        )
        asset_snippets = await self._search_asset_snippets(question)
        if asset_snippets:
            snippets = [*snippets, *asset_snippets]
            asset_lines = "\n".join(
                f"- {snippet.snippet} ({snippet.article_path})" for snippet in asset_snippets
            )
            asset_block = f"## Related images\n{asset_lines}"
            context = f"{context}\n\n{asset_block}" if context else asset_block
        context = self._compose_answer(hot_context, log_context, context, question)

        confidence = self._derive_query_confidence(
            index_matches=search_result.index_matches,
            seeds=search_result.seeds,
            snippets=snippets,
            article_count=len(related_articles),
        )
        retrieval_trace = self._build_retrieval_trace(
            index_matches=search_result.index_matches,
            seeds=search_result.seeds,
            sidecar_directories=search_result.sidecar_directories,
            article_paths=related_articles,
        )
        should_archive = (
            effective_query_config.auto_enhance_enabled
            and confidence >= effective_query_config.min_query_quality_score
        )

        return QueryResult(
            question=question,
            answer=context,
            related_articles=[str(a) for a in related_articles],
            should_archive=should_archive,
            confidence_score=confidence,
            source_snippets=snippets,
            retrieval_trace=retrieval_trace,
        )

    @staticmethod
    def _format_vault_prefix(hot_context: str, log_context: str) -> str:
        sections: list[str] = []
        if hot_context:
            sections.append(f"## Recent vault context\n{hot_context}")
        if log_context:
            sections.append(f"## Recent activity log\n{log_context}")
        return "\n\n".join(sections)

    @staticmethod
    def _compose_hot_only_answer(hot_context: str, log_context: str) -> str:
        """Return vault status when no articles match — do not pretend to answer the question."""
        prefix = WikiQueryEngine._format_vault_prefix(hot_context, log_context)
        base = "No matching wiki articles were found for this question."
        if prefix:
            return f"{base}\n\n{prefix}"
        return base

    @staticmethod
    def _compose_answer(hot_context: str, log_context: str, article_context: str, question: str) -> str:
        """Prefix wiki_query responses with hot.md and recent log.md when available (zero LLM)."""
        prefix = WikiQueryEngine._format_vault_prefix(hot_context, log_context)
        if prefix and article_context:
            return (
                f"{prefix}\n\n"
                f"## Retrieved articles for: {question}\n{article_context}"
            )
        if prefix:
            return prefix
        return article_context

    @staticmethod
    def _derive_query_confidence(
        *,
        index_matches: list[tuple[IndexRouteEntry, float]],
        seeds: list[RetrievalSeed],
        snippets: list[SourceSnippet],
        article_count: int,
    ) -> float:
        if article_count <= 0:
            return 0.0

        score = 0.45
        if index_matches:
            top_index_score = max(match_score for _entry, match_score in index_matches)
            score += min(0.25, top_index_score * 0.15)

        seed_sources = {seed.source for seed in seeds}
        if "index" in seed_sources:
            score += 0.1
        if "fts" in seed_sources:
            score += 0.08
        if "sidecar" in seed_sources:
            score += 0.05

        claim_snippets = [snippet for snippet in snippets if snippet.claim_id]
        if claim_snippets:
            quality_factors = [WikiQueryEngine._claim_snippet_quality_factor(snippet) for snippet in claim_snippets]
            score *= sum(quality_factors) / len(quality_factors)

        return round(min(1.0, max(0.05, score)), 3)

    @staticmethod
    def _claim_snippet_quality_factor(snippet: SourceSnippet) -> float:
        factor = 1.0
        snapshot_status = snippet.evidence_snapshot_status.strip()
        if snapshot_status == "stale":
            factor *= 0.6
        elif snapshot_status == "missing" and snippet.evidence_path.strip():
            factor *= 0.75

        claim_status = snippet.claim_status.strip().lower()
        if claim_status == "contested":
            factor *= 0.7
        elif claim_status == "unsupported":
            factor *= 0.5

        if snippet.claim_confidence > 0.0 and snippet.claim_confidence != 0.5:
            factor *= 1.0 + 0.1 * min(1.0, snippet.claim_confidence)
        return factor

    def _build_retrieval_trace(
        self,
        *,
        index_matches: list[tuple[IndexRouteEntry, float]],
        seeds: list[RetrievalSeed],
        sidecar_directories: list[str],
        article_paths: list[Path],
    ) -> WikiRetrievalTrace | None:
        if not index_matches and not seeds and not sidecar_directories and not article_paths:
            return None

        index_hits = tuple(
            WikiIndexTraceHit(
                link_name=entry.link_name,
                summary=entry.summary,
                score=match_score,
                page_type=entry.page_type,
            )
            for entry, match_score in index_matches[:8]
        )
        seed_traces = tuple(
            WikiRetrievalSeedTrace(
                concept_name=seed.concept_name,
                score=seed.score,
                source=seed.source,
            )
            for seed in seeds[:16]
        )
        selected_concepts = tuple(self._concept_name_from_path(path) for path in article_paths[:16])
        return WikiRetrievalTrace(
            index_hits=index_hits,
            seeds=seed_traces,
            sidecar_directories=tuple(sidecar_directories[:8]),
            selected_concepts=selected_concepts,
        )

    def _sidecar_directories_from_articles(self, article_paths: list[Path]) -> list[str]:
        ordered_dirs: list[str] = []
        seen_dirs: set[str] = set()
        for article in article_paths:
            try:
                rel = article.relative_to(self._structure.concepts_dir).with_suffix("")
            except ValueError:
                continue
            dir_path = "" if str(rel.parent) in (".", "") else str(rel.parent).replace("\\", "/")
            if not dir_path or dir_path in seen_dirs:
                continue
            seen_dirs.add(dir_path)
            ordered_dirs.append(dir_path)
        return ordered_dirs

    async def _search_concepts(
        self,
        query: str,
        query_config: WikiQueryConfig | None = None,
    ) -> _ConceptSearchResult:
        """Search for relevant concept articles via unified best-first convergence."""
        qc = query_config or self._query_config
        concepts = self._structure.list_concepts()
        if not concepts:
            return _ConceptSearchResult([], [], [], [])

        top_n = qc.max_context_articles
        index_matches = self._resolve_index_matches(query, qc)
        seed_names = [entry.link_name for entry, _score in index_matches]
        if index_matches:
            logger.info("wiki_index_route_hit=true seed_count=%d", len(seed_names))

        scoped_concepts = self._scope_concepts_for_index_seeds(concepts, seed_names)
        valid_names = (
            frozenset(self._concept_name_from_path(path) for path in scoped_concepts)
            if seed_names
            else None
        )
        seeds = await self._collect_retrieval_seeds(
            query,
            scoped_concepts,
            index_matches=index_matches,
            seed_names=seed_names,
            top_n=top_n,
            query_config=qc,
        )
        if not seeds:
            keyword_paths = self._keyword_search(query, scoped_concepts, top_n)
            sidecar_directories = self._sidecar_directories_from_articles(keyword_paths)
            return _ConceptSearchResult(keyword_paths, index_matches, [], sidecar_directories)

        expanded = converge_retrieval_candidates(
            query=query,
            query_config=qc,
            structure=self._structure,
            indexer=self._indexer,
            seeds=seeds,
            max_results=top_n,
            valid_names=valid_names,
        )
        if not expanded and qc.query_mode == "raw_claim":
            expanded = converge_retrieval_candidates(
                query=query,
                query_config=replace(qc, query_mode="auto"),
                structure=self._structure,
                indexer=self._indexer,
                seeds=seeds,
                max_results=top_n,
                valid_names=valid_names,
            )

        resolved: list[Path] = []
        seen_paths: set[Path] = set()
        for name in expanded:
            path = self._structure.get_concept_file_path(name)
            if path.exists() and path not in seen_paths:
                seen_paths.add(path)
                resolved.append(path)
        sidecar_directories = self._sidecar_directories_from_articles(resolved)
        return _ConceptSearchResult(resolved[:top_n], index_matches, seeds, sidecar_directories)

    async def _collect_retrieval_seeds(
        self,
        query: str,
        scoped_concepts: list[Path],
        *,
        index_matches: list[tuple[IndexRouteEntry, float]],
        seed_names: list[str],
        top_n: int,
        query_config: WikiQueryConfig,
    ) -> list[RetrievalSeed]:
        seeds: list[RetrievalSeed] = []
        seen: set[str] = set()

        def add_seed(name: str, score: float, source: str) -> None:
            normalized = self._normalize_concept_name(name)
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            seeds.append(RetrievalSeed(normalized, score, source))

        for entry, score in index_matches:
            add_seed(entry.link_name, score, "index")

        if query_config.sidecar_retrieval_enabled:
            sidecar_names = await self._collect_sidecar_seed_names(
                query,
                scoped_concepts,
                top_n=top_n,
                seed_names=seed_names,
                query_config=query_config,
            )
            for index, name in enumerate(sidecar_names):
                add_seed(name, max(0.4, 1.0 - index * 0.05), "sidecar")

        if self._config.enable_semantic_search:
            if self._search_fn is not None:
                try:
                    results = await self._search_fn(query, top_n)
                    for path, score in results[:top_n]:
                        add_seed(self._concept_name_from_path(path), float(score), "fts")
                except Exception as e:
                    logger.warning(f"Injected search_fn failed: {e}")

            try:
                results = await self._indexer.search(query, limit=max(top_n * 6, 20))
                for concept_name, score in results:
                    add_seed(concept_name, float(score), "fts")
                    if len(seeds) >= top_n * 3:
                        break
            except Exception as e:
                logger.warning(f"FTS5 semantic search failed: {e}")

        if len(seeds) < top_n:
            for path in self._keyword_search(query, scoped_concepts, top_n):
                add_seed(self._concept_name_from_path(path), 0.35, "keyword")

        return seeds

    def _resolve_index_matches(
        self,
        query: str,
        query_config: WikiQueryConfig | None = None,
    ) -> list[tuple[IndexRouteEntry, float]]:
        qc = query_config or self._query_config
        if not qc.index_first_enabled:
            return []
        entries = read_index_entries(self._structure)
        if not entries:
            return []
        return match_index_entries(
            query,
            entries,
            max_hits=max(1, qc.max_index_hits),
            min_score=qc.index_min_match_score,
        )

    def _scope_concepts_for_index_seeds(self, concepts: list[Path], seed_names: list[str]) -> list[Path]:
        if not seed_names:
            return concepts
        seed_dirs = self._directories_from_seed_names(seed_names)
        if not seed_dirs:
            return concepts
        scoped = self._collect_concepts_from_directory_scopes(seed_dirs, concepts)
        return scoped if scoped else concepts

    @staticmethod
    def _directories_from_seed_names(seed_names: list[str]) -> list[str]:
        ordered_dirs: list[str] = []
        seen_dirs: set[str] = set()
        for seed_name in seed_names:
            parent = Path(seed_name).parent
            if str(parent) in (".", ""):
                continue
            normalized = str(parent).replace("\\", "/").strip("/")
            if normalized and normalized not in seen_dirs:
                seen_dirs.add(normalized)
                ordered_dirs.append(normalized)
        return ordered_dirs

    async def _collect_sidecar_seed_names(
        self,
        query: str,
        concepts: list[Path],
        *,
        top_n: int,
        seed_names: list[str] | None = None,
        query_config: WikiQueryConfig | None = None,
    ) -> list[str]:
        """Use L0/L1 sidecars to collect concept seed names for best-first convergence."""
        qc = query_config or self._query_config
        limit = max(top_n * 3, 8)
        try:
            sidecar_hits = await self._indexer.search_sidecars(query, limit=limit)
        except Exception as e:
            logger.warning("Sidecar retrieval failed: %s", e)
            return []
        if not sidecar_hits:
            return []

        max_dirs = max(0, qc.max_sidecar_directories)
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
        if seed_names:
            for concept_name in seed_names:
                if concept_name in candidate_name_to_path and concept_name not in ranked_names:
                    ranked_names.append(concept_name)
                if len(ranked_names) >= top_n:
                    break
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
            return [name for name in ranked_names if name in candidate_name_to_path]
        return [self._concept_name_from_path(path) for path in candidates[:top_n]]

    def _expand_via_graph(self, seed_names: list[str], max_results: int) -> list[str]:
        """Expand seed results via best-first weighted graph convergence."""
        if not seed_names:
            return []

        seeds = [RetrievalSeed(name, 1.0, "index") for name in seed_names]
        return converge_retrieval_candidates(
            query="",
            query_config=self._query_config,
            structure=self._structure,
            indexer=self._indexer,
            seeds=seeds,
            max_results=max_results,
        )

    def _keyword_search(self, query: str, concepts: list[Path], top_n: int) -> list[Path]:
        """Score concepts by keyword overlap with query."""
        query_keywords = extract_query_terms(query)
        scored: list[tuple[Path, float]] = []

        for concept_path in concepts:
            try:
                content = concept_path.read_text(encoding="utf-8")
                content_keywords = extract_query_terms(content)
                overlap = len(query_keywords & content_keywords)
                score = overlap / max(len(query_keywords), 1)
                if score > 0:
                    scored.append((concept_path, score))
            except Exception as e:
                logger.warning("Failed to read %s: %s", concept_path, e)

        scored.sort(key=lambda x: x[1], reverse=True)
        return [path for path, _ in scored[:top_n]]

    async def _load_articles_context(
        self,
        article_paths: list[Path],
        index_matches: list[tuple[IndexRouteEntry, float]],
        query_config: WikiQueryConfig | None = None,
    ) -> tuple[str, list[SourceSnippet]]:
        """Load article content as context and extract citation snippets.

        Returns:
            Tuple of (context_string, list_of_source_snippets).
        """
        qc = query_config or self._query_config
        context_parts: list[str] = []
        snippets: list[SourceSnippet] = []
        remaining_chars = max(500, qc.max_context_chars)

        if index_matches:
            index_block = format_index_route_context(index_matches)
            if index_block:
                context_parts.append(index_block)
                remaining_chars = max(0, remaining_chars - len(index_block))
                top_entry, _score = index_matches[0]
                snippets.append(
                    SourceSnippet(
                        article_path=self._structure.get_index_catalog_relative_path(),
                        article_name="index",
                        snippet=f"[[{top_entry.link_name}]] — {top_entry.summary}",
                        section=INDEX_ROUTING_SECTION,
                        level="L0",
                    )
                )

        # Step 1: directory-level L0/L1 context
        if qc.sidecar_retrieval_enabled:
            sidecar_parts, sidecar_chars, sidecar_snippets = self._load_directory_sidecars(
                article_paths,
                query_config=qc,
            )
            if sidecar_parts:
                context_parts.extend(sidecar_parts)
                remaining_chars = max(0, remaining_chars - sidecar_chars)
            if sidecar_snippets:
                snippets.extend(sidecar_snippets)

        # Step 2: full article context (L2), bounded by count and hard char budget
        max_full_articles = max(1, min(len(article_paths), qc.max_full_articles))
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
                snippets.extend(self._claim_snippets_from_content(content, path))
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")

        return "\n\n---\n\n".join(context_parts), snippets

    def _load_directory_sidecars(
        self,
        article_paths: list[Path],
        query_config: WikiQueryConfig | None = None,
    ) -> tuple[list[str], int, list[SourceSnippet]]:
        qc = query_config or self._query_config
        parts: list[str] = []
        total_chars = 0
        snippets: list[SourceSnippet] = []
        seen: set[str] = set()
        max_dirs = max(0, qc.max_sidecar_directories)
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

    def _normalize_concept_name(self, name: str) -> str:
        """Map FTS/index aliases to the canonical on-disk concept relative path."""
        candidate = name.strip().replace("\\", "/")
        if not candidate:
            return ""
        path = self._structure.get_concept_file_path(candidate)
        if path.exists():
            return self._concept_name_from_path(path)
        return candidate

    @staticmethod
    def _sidecar_source_path(dir_path: str, *, level: str) -> str:
        filename = (
            WikiStructure.DIRECTORY_ABSTRACT_FILENAME if level == "L0" else WikiStructure.DIRECTORY_OVERVIEW_FILENAME
        )
        normalized = dir_path.strip("/")
        if not normalized:
            return f"/{filename}"
        return f"{normalized}/{filename}"

    def _claim_snippets_from_content(self, content: str, path: Path) -> list[SourceSnippet]:
        from ..core.claims_contract import (
            parse_claims_from_content,
            resolve_evidence_snapshot_and_excerpt,
        )

        claim_snippets: list[SourceSnippet] = []
        raw_bytes_cache: dict[str, bytes] = {}
        for claim in parse_claims_from_content(content):
            if claim.evidence:
                for evidence in claim.evidence:
                    snapshot_status, excerpt = resolve_evidence_snapshot_and_excerpt(
                        evidence.path,
                        evidence.lines,
                        evidence.content_sha256,
                        self._structure,
                        cache=raw_bytes_cache,
                    )
                    snippet_text = excerpt or claim.text
                    claim_snippets.append(
                        SourceSnippet(
                            article_path=str(path),
                            article_name=path.stem,
                            snippet=snippet_text,
                            section="Claim",
                            level="L2",
                            claim_id=claim.id,
                            claim_text=claim.text,
                            evidence_path=evidence.path,
                            line_range=evidence.lines,
                            claim_status=claim.status,
                            claim_confidence=claim.confidence,
                            evidence_content_sha256=evidence.content_sha256,
                            evidence_snapshot_status=snapshot_status,
                        )
                    )
            else:
                claim_snippets.append(
                    SourceSnippet(
                        article_path=str(path),
                        article_name=path.stem,
                        snippet=claim.text,
                        section="Claim",
                        level="L2",
                        claim_id=claim.id,
                        claim_text=claim.text,
                        claim_status=claim.status,
                        claim_confidence=claim.confidence,
                    )
                )
        return claim_snippets

    async def _search_asset_snippets(self, query: str) -> list[SourceSnippet]:
        if self._asset_indexer is None:
            return []
        hits = await self._asset_indexer.search(query, limit=3)
        snippets: list[SourceSnippet] = []
        for hit in hits:
            parent = hit.source_concepts[0] if hit.source_concepts else hit.filename
            snippets.append(
                SourceSnippet(
                    article_path=f"wiki/assets/{hit.filename}",
                    article_name=parent,
                    snippet=hit.caption,
                    section="Image",
                    level="L2",
                    hit_kind="asset",
                    asset_filename=hit.filename,
                )
            )
        return snippets

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
