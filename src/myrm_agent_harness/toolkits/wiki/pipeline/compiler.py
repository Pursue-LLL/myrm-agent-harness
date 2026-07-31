"""Wiki compiler - LLM as compiler for Karpathy-style knowledge base.

[INPUT]
langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
..core.config::WikiConfig, WikiCompileConfig (POS: Wiki configuration center)
..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
..core.types::ConceptInfo, CompileResult (POS: Wiki toolkit type definitions)
..core.parsers::parse_concepts_response (POS: LLM response parser)
.postprocess::generate_backlinks, save_metadata (POS: post-compilation steps)
.cognitive_map::WikiCognitiveMapService (POS: OKF index/log/hot writers)
.queue::WikiIngestionQueue (POS: persistent ingestion queue)
.sidecar::build_directory_sidecars (POS: bottom-up directory sidecar builder)

[OUTPUT]
WikiCompiler: LLM-Wiki compilation engine

[POS]
Wiki compilation core engine. Uses LLM to compile raw documents into structured wiki articles:
concept extraction and article generation. Post-compilation steps (index, backlinks, metadata)
and sidecar generation are delegated to dedicated modules. Supports incremental compilation,
Semaphore-limited parallel batch ingestion, and SQLite-based persistent controlled batch
processing.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.parsers import parse_concepts_response
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import CompileResult, ConceptInfo

from .cognitive_map import WikiCognitiveMapService, WikiMapEvent, WikiMapEventType
from .cognitive_map.schema_writer import read_index_context
from .contradiction_synthesis import run_contradiction_synthesis_pass
from .postprocess import generate_backlinks, save_metadata
from .queue import WikiIngestionQueue
from .resilience import CompileRunSnapshot, evaluate_batch_pause, resolve_io_failure, resolve_llm_failure
from .sidecar import build_directory_sidecars
from .survey import CompileSessionState, build_compile_survey

logger = get_agent_logger(__name__)


@dataclass(frozen=True, slots=True)
class _ArticleBatchStats:
    generated: int
    pending: int
    published: int
    blocked: int


@dataclass(frozen=True, slots=True)
class _BatchExtractOutcome:
    concepts: list[ConceptInfo]
    success_count: int
    failure_kinds: list[str]


class WikiCompiler:
    """
    LLM-powered wiki compiler (Karpathy architecture).

    Converts raw documents into structured, interconnected wiki articles.

    Features:
    - Incremental compilation (only process new/changed docs)
    - Parallel batch ingestion with Semaphore-limited concurrency
    - Persistent SQLite queue (prevents OOM and rate limit crashes)
    - Concept extraction and article generation with folder path context
    - Automatic index and Obsidian-compatible backlink generation
    """

    _active_workers: ClassVar[dict[str, asyncio.Task]] = {}
    _compile_sessions: ClassVar[dict[str, CompileSessionState]] = {}

    def __init__(
        self,
        llm: BaseChatModel,
        structure: WikiStructure,
        config: WikiConfig,
        compile_config: WikiCompileConfig | None = None,
        indexer: WikiIndexer | None = None,
    ):
        self._llm = llm
        self._structure = structure
        self._config = config
        self._compile_config = compile_config or WikiCompileConfig()
        self._indexer = indexer
        self._queue = WikiIngestionQueue(structure)
        self._structure.ensure_structure()
        self._parallel = config.parallel_compilation
        self._semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(config.max_parallel_workers) if self._parallel else None
        )

    def _session_key(self) -> str:
        return str(self._structure.base_dir)

    def _get_session(self) -> CompileSessionState | None:
        return self.__class__._compile_sessions.get(self._session_key())

    def _clear_compile_session(self) -> None:
        self.__class__._compile_sessions.pop(self._session_key(), None)
        self._queue.set_compile_phase("idle")

    def _maybe_clear_compile_session(self) -> None:
        queue_stats = self._queue.get_stats()
        if queue_stats.get("pending", 0) == 0 and queue_stats.get("processing", 0) == 0:
            self._clear_compile_session()

    def _ensure_compile_session(self) -> CompileSessionState:
        existing = self._get_session()
        if existing is not None:
            return existing

        pending_paths = [Path(path) for path in self._queue.list_pending_file_paths()]
        self._queue.set_compile_phase("structure_survey")
        context = build_compile_survey(
            self._structure,
            pending_paths,
            fast_path_scope_paths=self._structure.list_raw_files(),
        )
        session = CompileSessionState(context=context)
        self.__class__._compile_sessions[self._session_key()] = session
        self._queue.set_compile_phase(
            "semantic_compile",
            facet_count=context.facet_count,
            warning_count=context.warning_count,
            survey_skipped=context.skipped,
        )
        logger.info(
            "Compile survey ready: skipped=%s facets=%d warnings=%d pending=%d",
            context.skipped,
            context.facet_count,
            context.warning_count,
            len(pending_paths),
        )
        return session

    def _relative_raw_path(self, doc_path: Path) -> str:
        try:
            return doc_path.relative_to(self._structure.base_dir).as_posix()
        except ValueError:
            return doc_path.name

    def _sort_queue_items_for_survey(self, queue_items: list[dict]) -> list[dict]:
        session = self._get_session()
        if session is None or session.context.skipped:
            return queue_items

        order_index = {
            facet_id: index for index, facet_id in enumerate(session.context.processing_order)
        }

        def _sort_key(item: dict) -> tuple[int, str]:
            rel = self._relative_raw_path(Path(str(item["file_path"])))
            facet_id = session.context.path_to_facet.get(rel, "")
            return (order_index.get(facet_id, len(order_index)), rel)

        return sorted(queue_items, key=_sort_key)

    def _build_extract_survey_context(self, relative_path: str) -> str:
        session = self._get_session()
        if session is None or session.context.skipped:
            return ""

        sections: list[str] = []
        facet_id = session.context.path_to_facet.get(relative_path)
        if facet_id is not None:
            facet = session.context.facets.get(facet_id)
            if facet is not None:
                sections.append(f"# Compile Facet: {facet.folder_path}")
                seed_lines = [
                    *session.facet_seeds.get(facet_id, []),
                    *list(facet.suggested_seeds),
                ]
                unique_seeds = list(dict.fromkeys(seed for seed in seed_lines if seed))[:12]
                if unique_seeds:
                    sections.append(
                        "# Facet concept seeds (reuse these names when applicable):\n"
                        + "\n".join(f"- {seed}" for seed in unique_seeds)
                    )

        chunk_group_id = session.context.path_to_chunk_group.get(relative_path)
        if chunk_group_id is not None:
            siblings = session.context.chunk_groups.get(chunk_group_id, ())
            if len(siblings) > 1:
                sections.append(
                    f"# Chunk group ({len(siblings)} parts of one source document)\n"
                    "Extract concepts once for the whole group; prefer one shared concept path.\n"
                    + "\n".join(f"- {path}" for path in siblings[:20])
                )

        if not sections:
            return ""
        return "\n\n".join(sections) + "\n\n"

    def _record_facet_seeds(self, queue_items: list[dict], concepts: list[ConceptInfo]) -> None:
        session = self._get_session()
        if session is None or session.context.skipped or not concepts:
            return

        batch_paths = {self._relative_raw_path(Path(str(item["file_path"]))) for item in queue_items}
        for concept in concepts:
            for source in concept.source_files:
                if source not in batch_paths:
                    continue
                facet_id = session.context.path_to_facet.get(source)
                if facet_id is None:
                    continue
                seeds = session.facet_seeds.setdefault(facet_id, [])
                if concept.name not in seeds:
                    seeds.append(concept.name)

    def enqueue_file(self, file_path: Path) -> None:
        """Enqueue a raw file for compilation and ensure the background worker is running.

        Also indexes the raw text into FTS5 for immediate searchability
        before compilation completes.
        """
        self._queue.add_item(file_path)

        if self._indexer and file_path.exists() and file_path.suffix == ".md":
            try:
                raw_text = file_path.read_text(encoding="utf-8")
                if raw_text.strip():
                    self._indexer.index_raw_text(file_path.stem, raw_text)
            except Exception as e:
                logger.warning(f"Failed to index raw text for {file_path.name}: {e}")

        self.start_background_worker()

    def get_compile_run(self) -> CompileRunSnapshot:
        return self._queue.get_compile_run()

    def resume_compile_worker(self) -> None:
        self._queue.resume_compile()
        self.start_background_worker()

    def start_background_worker(self) -> None:
        """Start a background worker to continuously drain the ingestion queue."""

        user_key = str(self._structure.base_dir)

        if user_key in self.__class__._active_workers:
            task = self.__class__._active_workers[user_key]
            if not task.done():
                logger.debug(f"Worker already running for {user_key}")
                return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("No running event loop; background worker will start on first compile")
            return

        task = loop.create_task(self._worker_loop())
        self.__class__._active_workers[user_key] = task
        logger.info(f"Started background wiki worker for {user_key}")

    async def _worker_loop(self) -> None:

        user_key = str(self._structure.base_dir)
        consecutive_empty = 0

        recovered = self._queue.reset_stale_processing()
        if recovered:
            logger.info(f"Recovered {recovered} stale processing items back to pending")

        try:
            while consecutive_empty < 3:  # Exit after 3 empty checks (15s idle)
                if self._queue.is_compile_paused():
                    await asyncio.sleep(5)
                    consecutive_empty += 1
                    continue

                pending_items = self._queue.get_pending_items(limit=5)

                if not pending_items:
                    retryable = self._queue.get_transient_retryable_items(max_retries=3, limit=3)
                    if retryable:
                        for item in retryable:
                            self._queue.reset_for_retry(item["id"])
                        logger.info(f"Auto-retrying {len(retryable)} transient failed items")
                        consecutive_empty = 0
                        continue

                    consecutive_empty += 1
                    await asyncio.sleep(5)
                    continue

                consecutive_empty = 0
                logger.info(f"Worker draining {len(pending_items)} items from queue...")

                self._ensure_compile_session()
                self._queue.set_compile_phase("semantic_compile")
                batch_outcome = await self._extract_concepts_batch(pending_items)
                should_pause, pause_reason, primary_kind = evaluate_batch_pause(
                    success_count=batch_outcome.success_count,
                    failure_kinds=batch_outcome.failure_kinds,
                )
                if should_pause:
                    self._queue.pause_compile(pause_reason, primary_kind)
                    logger.warning("Compile worker paused: %s", pause_reason)
                    continue

                all_concepts = batch_outcome.concepts
                if all_concepts:
                    self._queue.set_compile_phase("postprocess")
                    articles = await self._generate_articles_batch(all_concepts)
                    synthesis_result = await run_contradiction_synthesis_pass(
                        self._llm,
                        self._structure,
                        self._compile_config,
                        self._indexer,
                        all_concepts,
                    )
                    if synthesis_result.synthesis_staged:
                        logger.info(
                            "CCSP staged %s evolution page(s) from %s pair(s)",
                            synthesis_result.synthesis_staged,
                            synthesis_result.pairs_considered,
                        )
                    self._refresh_cognitive_map(all_concepts, batch=True)
                    if self._config.enable_backlinks:
                        await self._generate_backlinks(all_concepts)
                    if self._config.enable_directory_sidecars:
                        await self._build_sidecars(all_concepts)
                    await self._save_metadata(len(all_concepts), articles)
                    await self._maybe_commit_vault_git("compile batch")

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Wiki worker loop failed: {e}")
        finally:
            self._maybe_clear_compile_session()
            if user_key in self.__class__._active_workers:
                del self.__class__._active_workers[user_key]
            logger.info(f"Wiki background worker stopped for {user_key}")

    async def compile_all(self, batch_size: int = 10) -> CompileResult:
        """
        Compile all raw documents to wiki using the persistent queue.

        Returns:
            CompileResult with statistics
        """
        start_time = datetime.now(UTC)
        raw_files = self._structure.list_raw_files()

        # Step 0: Add files to queue based on strategy
        if self._config.compile_strategy == "incremental":
            changed_files = await self._filter_changed_files(raw_files)
            logger.info(f"Incremental compile: adding {len(changed_files)} changed files to queue")
            if changed_files:
                self._queue.add_batch(changed_files)
        else:
            logger.info(f"Full compile: adding {len(raw_files)} files to queue")
            if raw_files:
                self._queue.add_batch(raw_files)

        pending_items = self._queue.get_pending_items(limit=batch_size)

        if self._queue.is_compile_paused():
            logger.warning("Compile requested while circuit is paused; skipping batch drain")
            return CompileResult(
                concepts_count=0,
                articles_generated=0,
                backlinks_created=0,
                duration_ms=int((datetime.now(UTC) - start_time).total_seconds() * 1000),
                articles_pending=0,
                articles_published=0,
                articles_blocked=0,
                synthesis_pending=0,
            )

        if not pending_items:
            logger.info("No pending files to compile in queue")
            self._refresh_cognitive_map([], summary="Compile requested; ingestion queue empty")
            return CompileResult(
                concepts_count=0,
                articles_generated=0,
                backlinks_created=0,
                duration_ms=0,
                articles_pending=0,
                articles_published=0,
                articles_blocked=0,
                synthesis_pending=0,
            )

        logger.info(f"Processing batch of {len(pending_items)} files from queue")

        self._ensure_compile_session()
        self._queue.set_compile_phase("semantic_compile")

        # Step 1: Extract concepts sequentially from the queue batch
        batch_outcome = await self._extract_concepts_batch(pending_items)
        should_pause, pause_reason, primary_kind = evaluate_batch_pause(
            success_count=batch_outcome.success_count,
            failure_kinds=batch_outcome.failure_kinds,
        )
        if should_pause:
            self._queue.pause_compile(pause_reason, primary_kind)
        all_concepts = batch_outcome.concepts
        logger.info(f"Extracted {len(all_concepts)} concepts from batch")

        if all_concepts:
            self._queue.set_compile_phase("postprocess")
        else:
            self._queue.set_compile_phase("semantic_compile")

        # Step 2: Generate articles for each concept
        batch_stats = await self._generate_articles_batch(all_concepts)
        logger.info(
            "Generated %s articles (published=%s pending=%s blocked=%s)",
            batch_stats.generated,
            batch_stats.published,
            batch_stats.pending,
            batch_stats.blocked,
        )

        synthesis_result = await run_contradiction_synthesis_pass(
            self._llm,
            self._structure,
            self._compile_config,
            self._indexer,
            all_concepts,
        )
        if synthesis_result.synthesis_staged:
            logger.info(
                "CCSP staged %s evolution page(s) from %s pair(s)",
                synthesis_result.synthesis_staged,
                synthesis_result.pairs_considered,
            )

        # Step 3: Refresh OKF cognitive map (index/log/hot)
        self._refresh_cognitive_map(all_concepts, batch=True)

        # Step 4: Generate backlinks
        backlinks_count = 0
        if self._config.enable_backlinks:
            backlinks_count = await self._generate_backlinks(all_concepts)
            logger.info(f"Created {backlinks_count} backlinks")

        # Step 5: Build directory sidecars (L0/L1)
        if self._config.enable_directory_sidecars:
            await self._build_sidecars(all_concepts)

        # Step 6: Update metadata
        await self._save_metadata(len(all_concepts), batch_stats.generated)

        await self._maybe_commit_vault_git("compile")

        self._maybe_clear_compile_session()

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

        # Start background worker to drain the rest of the queue if any
        self.start_background_worker()

        return CompileResult(
            concepts_count=len(all_concepts),
            articles_generated=batch_stats.generated,
            backlinks_created=backlinks_count,
            duration_ms=duration_ms,
            articles_pending=batch_stats.pending,
            articles_published=batch_stats.published,
            articles_blocked=batch_stats.blocked,
            synthesis_pending=synthesis_result.synthesis_staged,
        )

    async def _filter_changed_files(self, raw_files: list[Path]) -> list[Path]:
        """Filter for new or changed files using SHA256 content hashing."""
        metadata_path = self._structure.get_wiki_metadata_path()
        if not metadata_path.exists():
            return raw_files

        try:
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)
            from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
                get_last_compile_raw_hashes,
                raw_relative_storage_key,
            )

            known_hashes = get_last_compile_raw_hashes(metadata)
        except Exception as e:
            logger.warning(f"Failed to read metadata: {e}")
            return raw_files

        changed: list[Path] = []
        for f in raw_files:
            try:
                content_hash = hashlib.sha256(f.read_bytes()).hexdigest()
                storage_key = raw_relative_storage_key(self._structure, f)
                if known_hashes.get(storage_key) != content_hash:
                    changed.append(f)
            except OSError:
                changed.append(f)
        return changed

    async def _extract_concepts_batch(self, queue_items: list[dict]) -> _BatchExtractOutcome:
        """Extract concepts from queue items with configurable parallelism."""
        queue_items = self._sort_queue_items_for_survey(queue_items)
        failure_kinds: list[str] = []
        success_count = 0

        async def _process_single_item(item: dict) -> list[ConceptInfo]:
            nonlocal success_count
            item_id = item["id"]
            raw_file = Path(item["file_path"])
            self._queue.mark_processing(item_id)
            try:
                if not raw_file.exists():
                    resolution = resolve_io_failure("File not found")
                    self._queue.mark_failed(
                        item_id,
                        "File not found",
                        error_kind=resolution.error_kind,
                    )
                    return []
                if self._semaphore:
                    async with self._semaphore:
                        concepts = await self._extract_concepts_from_doc(raw_file)
                else:
                    concepts = await self._extract_concepts_from_doc(raw_file)
                if not concepts:
                    resolution = resolve_llm_failure(RuntimeError("Concept extraction returned no concepts"))
                    self._queue.mark_failed(
                        item_id,
                        "Concept extraction returned no concepts",
                        error_kind=resolution.error_kind,
                        retry_after_seconds=resolution.retry_after_seconds,
                    )
                    failure_kinds.append(resolution.error_kind)
                    return []
                self._queue.mark_completed(item_id)
                success_count += 1
                return concepts
            except Exception as e:
                logger.error(f"Failed to extract concepts from {raw_file}: {e}")
                resolution = resolve_llm_failure(e)
                self._queue.mark_failed(
                    item_id,
                    str(e),
                    error_kind=resolution.error_kind,
                    retry_after_seconds=resolution.retry_after_seconds,
                )
                failure_kinds.append(resolution.error_kind)
                return []

        if self._parallel:
            results = await asyncio.gather(
                *[_process_single_item(item) for item in queue_items],
                return_exceptions=True,
            )
        else:
            results = [await _process_single_item(item) for item in queue_items]

        all_concepts: dict[str, ConceptInfo] = {}
        for result in results:
            if isinstance(result, BaseException):
                logger.error(f"Unexpected error in concept extraction: {result}")
                resolution = resolve_llm_failure(result)
                failure_kinds.append(resolution.error_kind)
                continue
            for concept in result:
                if concept.name in all_concepts:
                    existing = all_concepts[concept.name]
                    all_concepts[concept.name] = ConceptInfo(
                        name=concept.name,
                        definition=concept.definition,
                        mentions=existing.mentions + concept.mentions,
                        source_files=list(set(existing.source_files + concept.source_files)),
                        related_concepts=list(set(existing.related_concepts + concept.related_concepts)),
                    )
                else:
                    all_concepts[concept.name] = concept

        self._record_facet_seeds(queue_items, list(all_concepts.values()))

        return _BatchExtractOutcome(
            concepts=list(all_concepts.values()),
            success_count=success_count,
            failure_kinds=failure_kinds,
        )

    async def _extract_concepts_from_doc(self, doc_path: Path) -> list[ConceptInfo]:
        """Extract concepts from a single document using LLM, with path as context."""
        try:
            content = doc_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read {doc_path}: {e}")
            return []

        # Include relative path as context (e.g. docs/architecture.md vs notes/daily.md)
        relative_path = self._relative_raw_path(doc_path)

        survey_context = self._build_extract_survey_context(relative_path)
        index_context = read_index_context(self._structure)
        index_block = ""
        if index_context:
            index_block = f"# Existing wiki catalog (reuse these concept names when applicable):\n{index_context}\n\n"
        prompt = self._compile_config.extract_concepts_prompt_template
        system_msg = SystemMessage(content="You are a knowledge extraction expert.")
        human_msg = HumanMessage(
            content=(
                f"{prompt}\n\n{survey_context}{index_block}# Document Path: {relative_path}\n# Document Content:\n\n{content}"
            )
        )

        try:
            response = await self._llm.ainvoke([system_msg, human_msg])
            raw_content = response.content
            if inspect.isawaitable(raw_content):
                raw_content = await raw_content
            response_text = str(raw_content)
            logger.info(f"LLM extraction response for {doc_path}: {response_text}")
            concepts = parse_concepts_response(response_text, str(relative_path))
            return concepts
        except Exception as e:
            logger.error(f"LLM extraction failed for {doc_path}: {e}")
            raise

    async def _generate_articles_batch(self, concepts: list[ConceptInfo]) -> _ArticleBatchStats:
        """Generate wiki articles with configurable parallelism."""
        filtered = [c for c in concepts if c.mentions >= self._compile_config.min_concept_mentions]
        logger.info(f"Generating articles for {len(filtered)} concepts")

        async def _gen_one(concept: ConceptInfo) -> str:
            try:
                if self._semaphore:
                    async with self._semaphore:
                        return await self._generate_article(concept)
                return await self._generate_article(concept)
            except Exception as e:
                logger.error(f"Failed to generate article for {concept.name}: {e}")
                return "blocked"

        if self._parallel:
            results = await asyncio.gather(
                *[_gen_one(c) for c in filtered],
                return_exceptions=True,
            )
        else:
            results = [await _gen_one(c) for c in filtered]

        pending = 0
        published = 0
        blocked = 0
        for result in results:
            if isinstance(result, BaseException):
                blocked += 1
                continue
            if result == "pending":
                pending += 1
            elif result == "published":
                published += 1
            else:
                blocked += 1

        generated = pending + published
        return _ArticleBatchStats(
            generated=generated,
            pending=pending,
            published=published,
            blocked=blocked,
        )

    async def _generate_article(self, concept: ConceptInfo) -> str:
        """Generate wiki article for a concept in Obsidian format."""
        article_path = self._structure.get_concept_file_path(concept.name)
        existing_content = ""
        if article_path.exists():
            existing_content = article_path.read_text(encoding="utf-8")

        purpose_context = ""
        purpose_path = self._structure.get_purpose_path()
        if purpose_path.exists():
            purpose_text = purpose_path.read_text(encoding="utf-8").strip()
            if purpose_text:
                purpose_context = f"Knowledge base direction: {purpose_text}\nFocus your article within this scope.\n\n"

        prompt = self._compile_config.generate_article_prompt_template.format(
            concept_name=concept.name,
            purpose_context=purpose_context,
            source_docs="\n".join(f"- {f}" for f in concept.source_files),
        )

        if existing_content:
            prompt += f"\n\n# Existing Wiki Content\nPlease update the Compiled Truth section using the new source documents, but MUST PRESERVE the existing Timeline and APPEND new evidence to the bottom of the Timeline:\n\n{existing_content}"

        system_msg = SystemMessage(content="You are a technical writer creating wiki articles.")
        human_msg = HumanMessage(content=prompt)

        try:
            response = await self._llm.ainvoke([system_msg, human_msg])
            raw_content = response.content
            if inspect.isawaitable(raw_content):
                raw_content = await raw_content
            article_content = str(raw_content)

            if len(article_content) > self._compile_config.max_article_length:
                article_content = article_content[: self._compile_config.max_article_length] + "\n\n(truncated)"

            from ..core.frontmatter_contract import apply_compile_gate

            article_content = apply_compile_gate(
                article_content,
                concept.name,
                concept.source_files,
            )

            from ..core.claims_contract import ensure_compile_claims

            article_content = ensure_compile_claims(
                article_content,
                concept.name,
                list(concept.source_files),
                structure=self._structure,
            )

            if self._compile_config.require_approval:
                from .pending import WikiPendingEditsManager

                pending_mgr = WikiPendingEditsManager(self._structure, self._indexer)
                await pending_mgr.stage_pending_edit(
                    concept.name,
                    article_content,
                    source_files=concept.source_files,
                )
                logger.info(f"Generated pending draft for article: {concept.name}")
                return "pending"

            from .publication import publish_concept_article

            await publish_concept_article(
                self._structure,
                self._indexer,
                concept.name,
                article_content,
            )
            logger.info(f"Generated and published article: {concept.name}")
            return "published"

        except Exception as e:
            logger.error(f"Failed to generate article for {concept.name}: {e}")
            raise

    def _cognitive_map_service(self) -> WikiCognitiveMapService:
        stats = self._queue.get_stats()
        pending_queue = stats.get("pending", 0)
        return WikiCognitiveMapService(
            self._structure,
            get_queue_pending=lambda: pending_queue,
        )

    def _refresh_cognitive_map(
        self,
        concepts: list[ConceptInfo],
        *,
        batch: bool = False,
        summary: str | None = None,
    ) -> None:
        """Rebuild OKF index/log/hot after compilation."""
        if summary is None:
            summary = (
                f"Compiled batch finished ({len(concepts)} concept(s) extracted)"
                if batch
                else f"Compiled {len(concepts)} concept(s)"
            )
        event = WikiMapEvent(
            event_type=WikiMapEventType.COMPILE,
            summary=summary,
            details={"concepts_extracted": len(concepts)},
        )
        self._cognitive_map_service().refresh(event)

    async def _generate_backlinks(self, concepts: list[ConceptInfo]) -> int:
        """Delegate to postprocess.generate_backlinks."""
        return await generate_backlinks(self._structure, self._config, concepts, self._indexer)

    async def _save_metadata(self, concepts_count: int, articles_count: int) -> None:
        """Delegate to postprocess.save_metadata."""
        await save_metadata(self._structure, concepts_count, articles_count)

    async def _build_sidecars(self, concepts: list[ConceptInfo]) -> None:
        """Build L0/L1 directory sidecars via incremental bottom-up DAG."""
        result = await build_directory_sidecars(
            self._llm,
            self._structure,
            self._compile_config,
            touched_concepts=concepts,
            indexer=self._indexer,
        )
        logger.info(
            "Directory sidecars built: rebuilt=%d skipped=%d removed=%d",
            result.rebuilt_directories,
            result.skipped_directories,
            result.removed_directories,
        )

    async def _maybe_commit_vault_git(self, reason: str) -> None:
        from ..portability.vault_git import maybe_commit_vault_git_snapshot

        await asyncio.to_thread(
            maybe_commit_vault_git_snapshot,
            self._structure,
            self._config,
            reason=reason,
        )
