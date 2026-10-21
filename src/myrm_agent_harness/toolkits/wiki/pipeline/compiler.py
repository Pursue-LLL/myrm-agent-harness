"""Wiki compiler - LLM as compiler for Karpathy-style knowledge base.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- ..core.config::WikiConfig, WikiCompileConfig (POS: Wiki configuration center)
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- ..core.types::ConceptInfo, CompileResult (POS: Wiki toolkit type definitions)
- .postprocess::generate_backlinks, save_metadata (POS: post-compilation steps)
- .cognitive_map::WikiCognitiveMapService (POS: OKF index/log/hot writers)
- .articles::ArticleBatchStats, generate_article, generate_articles_batch (POS: the article stage of a compile)
- .batch_settle::blocked_sources, fail_extracted, pause_on_failures, settle_extracted (POS: settles a batch's queue rows once its results are saved, pauses on failing stages)
- .compiler_enqueue::enqueue_changed_sources (POS: compile intake, which raw files go onto the queue)
- .compiler_extraction::BatchExtractOutcome, extract_concepts_batch, extract_concepts_from_doc, relative_raw_path (POS: the concept extraction stage of a batch)
- .queue::WikiIngestionQueue (POS: persistent ingestion queue)
- .sidecar::build_directory_sidecars (POS: bottom-up directory sidecar builder)

[OUTPUT]
- WikiCompiler: LLM-Wiki compilation engine

[POS]
Wiki compilation core engine. Uses LLM to compile raw documents into structured wiki articles:
concept extraction and article generation. Post-compilation steps (index, backlinks, metadata)
and sidecar generation are delegated to dedicated modules. Supports incremental compilation,
Semaphore-limited parallel batch ingestion, and SQLite-based persistent controlled batch
processing.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import CompileResult, ConceptInfo

from . import compiler_enqueue
from .articles import ArticleBatchStats, generate_article, generate_articles_batch
from .batch_settle import blocked_sources, fail_extracted, pause_on_failures, settle_extracted
from .cognitive_map import WikiCognitiveMapService, WikiMapEvent, WikiMapEventType
from .compiler_extraction import (
    BatchExtractOutcome,
    extract_concepts_batch,
    extract_concepts_from_doc,
    relative_raw_path,
)
from .contradiction_synthesis import run_contradiction_synthesis_pass
from .postprocess import generate_backlinks, save_metadata
from .queue import QueueItem, WikiIngestionQueue
from .resilience import CompileRunSnapshot
from .sidecar import build_directory_sidecars
from .survey import CompileSessionState, build_compile_survey

logger = get_agent_logger(__name__)


@dataclass(frozen=True, slots=True)
class _BatchReport:
    concepts_count: int
    articles: ArticleBatchStats
    synthesis_staged: int = 0
    backlinks_created: int = 0
    embed_paused: bool = False


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

    _active_workers: ClassVar[dict[str, asyncio.Task[Any]]] = {}
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
        self._semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(config.max_parallel_workers) if config.parallel_compilation else None
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

                await self._run_batch(pending_items, commit_reason="compile batch", postprocess_empty=False)
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Wiki worker loop failed: {e}")
        finally:
            self._maybe_clear_compile_session()
            if user_key in self.__class__._active_workers:
                del self.__class__._active_workers[user_key]
            logger.info(f"Wiki background worker stopped for {user_key}")

    async def enqueue_changed_sources(self) -> int:
        """Queue the raw files a compile has to read; the background worker (``start_background_worker``) drains them.

        Returns:
            How many files were queued.
        """
        return await compiler_enqueue.enqueue_changed_sources(
            self._structure, self._queue, incremental=self._config.compile_strategy == "incremental"
        )

    async def compile_all(self, batch_size: int = 10) -> CompileResult:
        """
        Compile all raw documents to wiki using the persistent queue.

        Returns:
            CompileResult with statistics
        """
        start_time = datetime.now(UTC)

        # Step 0: Add files to queue based on strategy
        await self.enqueue_changed_sources()

        pending_items = self._queue.get_pending_items(limit=batch_size)

        if self._queue.is_compile_paused():
            logger.warning("Compile requested while circuit is paused; skipping batch drain")
            return CompileResult(
                concepts_count=0,
                articles_generated=0,
                backlinks_created=0,
                duration_ms=int((datetime.now(UTC) - start_time).total_seconds() * 1000),
            )

        if not pending_items:
            logger.info("No pending files to compile in queue")
            self._refresh_cognitive_map([], summary="Compile requested; ingestion queue empty")
            return CompileResult(concepts_count=0, articles_generated=0, backlinks_created=0)

        logger.info(f"Processing batch of {len(pending_items)} files from queue")

        report = await self._run_batch(pending_items, commit_reason="compile", postprocess_empty=True)
        articles = report.articles

        duration_ms = 0
        if not report.embed_paused:
            self._maybe_clear_compile_session()
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            # Start background worker to drain the rest of the queue if any
            self.start_background_worker()

        return CompileResult(
            concepts_count=report.concepts_count,
            articles_generated=articles.generated,
            backlinks_created=report.backlinks_created,
            duration_ms=duration_ms,
            articles_pending=articles.pending,
            articles_published=articles.published,
            articles_blocked=articles.blocked,
            synthesis_pending=report.synthesis_staged,
        )

    async def _run_batch(self, items: list[QueueItem], *, commit_reason: str, postprocess_empty: bool) -> _BatchReport:
        """Compile one batch of queue items from extraction to the vault snapshot; the worker and ``compile_all`` both run it.

        The batch's sources stay ``processing`` until everything the compile writes for them is saved, so the
        queue reports work in progress for as long as there is some, and a process that dies midway leaves them for
        the next one to requeue; a source whose file changed meanwhile is queued again instead of completed.
        ``postprocess_empty`` also runs the post-extraction steps (cognitive map, metadata) when no concept was
        extracted, as ``compile_all`` does and the worker does not.

        Raises:
            Exception: whatever failed after extraction, after the batch's sources were marked failed.
        """
        self._ensure_compile_session()
        self._queue.set_compile_phase("semantic_compile")
        with self._queue.keep_alive([item["id"] for item in items]):
            outcome = await self._extract_concepts_batch(items)
            pause_on_failures(self._queue, success_count=outcome.success_count, failure_kinds=outcome.failure_kinds)
            concepts = outcome.concepts
            logger.info(f"Extracted {len(concepts)} concepts from batch")
            if not concepts and not postprocess_empty:
                return _BatchReport(0, ArticleBatchStats(generated=0, pending=0, published=0, blocked=0))

            self._queue.set_compile_phase("postprocess" if concepts else "semantic_compile")
            try:
                report = await self._postprocess_batch(concepts)
            except Exception as e:
                logger.error(f"Postprocess failed, marking {len(outcome.read_hashes)} source(s) failed: {e}")
                fail_extracted(self._queue, list(outcome.read_hashes), e)
                raise
            item_ids_by_source = {
                relative_raw_path(self._structure, Path(item["file_path"])): item["id"] for item in items
            }
            blocked = blocked_sources(item_ids_by_source, report.articles.failures)
            settle_extracted(self._queue, items, outcome.read_hashes, blocked)

        if not report.embed_paused:
            await self._maybe_commit_vault_git(commit_reason)
        return report

    async def _postprocess_batch(self, concepts: list[ConceptInfo]) -> _BatchReport:
        """Write everything a batch's concepts produce: articles, evolution pages, map, backlinks, sidecars, metadata."""
        articles = await self._generate_articles_batch(concepts)
        self._maybe_pause_for_embed_failure(articles)
        self._maybe_pause_for_failed_articles(articles)
        logger.info(
            "Generated %s articles (published=%s pending=%s blocked=%s)",
            articles.generated,
            articles.published,
            articles.pending,
            articles.blocked,
        )
        if articles.embed_pause_kind:
            return _BatchReport(len(concepts), articles, embed_paused=True)

        synthesis_result = await run_contradiction_synthesis_pass(
            self._llm,
            self._structure,
            self._compile_config,
            self._indexer,
            concepts,
        )
        if synthesis_result.synthesis_staged:
            logger.info(
                "CCSP staged %s evolution page(s) from %s pair(s)",
                synthesis_result.synthesis_staged,
                synthesis_result.pairs_considered,
            )

        self._refresh_cognitive_map(concepts, batch=True)

        backlinks_count = 0
        if self._config.enable_backlinks:
            backlinks_count = await self._generate_backlinks(concepts)
            logger.info(f"Created {backlinks_count} backlinks")
        if self._config.enable_directory_sidecars:
            await self._build_sidecars(concepts)

        await self._save_metadata(len(concepts), articles.generated)
        return _BatchReport(len(concepts), articles, synthesis_result.synthesis_staged, backlinks_count)

    async def _extract_concepts_batch(self, queue_items: list[QueueItem]) -> BatchExtractOutcome:
        """Delegate to compiler_extraction.extract_concepts_batch."""
        return await extract_concepts_batch(
            queue_items,
            queue=self._queue,
            structure=self._structure,
            get_session=self._get_session,
            semaphore=self._semaphore,
            extract_doc=self._extract_concepts_from_doc,
        )

    async def _extract_concepts_from_doc(self, doc_path: Path) -> list[ConceptInfo]:
        """Delegate to compiler_extraction.extract_concepts_from_doc."""
        return await extract_concepts_from_doc(
            self._llm, self._structure, self._compile_config, self._get_session(), doc_path
        )

    async def _generate_articles_batch(self, concepts: list[ConceptInfo]) -> ArticleBatchStats:
        """Delegate to articles.generate_articles_batch."""
        return await generate_articles_batch(
            concepts,
            self._generate_article,
            min_mentions=self._compile_config.min_concept_mentions,
            semaphore=self._semaphore,
        )

    async def _generate_article(self, concept: ConceptInfo) -> str:
        """Delegate to articles.generate_article."""
        return await generate_article(self._llm, self._structure, self._compile_config, self._indexer, concept)

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
        pending_queue = self._queue.get_stats().get("pending", 0)
        WikiCognitiveMapService(self._structure, get_queue_pending=lambda: pending_queue).refresh(event)

    def _maybe_pause_for_embed_failure(self, stats: ArticleBatchStats) -> None:
        if not stats.embed_pause_kind:
            return
        self._queue.pause_compile(stats.embed_pause_reason, stats.embed_pause_kind)
        logger.warning("Compile worker paused: %s", stats.embed_pause_reason)

    def _maybe_pause_for_failed_articles(self, stats: ArticleBatchStats) -> None:
        """Pause when no article of the batch was written and the failures say more would fail too.

        The extraction step applies the same rule to its own failures. An embed pause has already stopped the
        compile with the reason the user can act on, so it is not overwritten.
        """
        if stats.embed_pause_kind:
            return
        pause_on_failures(
            self._queue,
            success_count=stats.generated,
            failure_kinds=[failure.resolution.error_kind for failure in stats.failures],
        )

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
