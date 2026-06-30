"""Wiki compiler - LLM as compiler for Karpathy-style knowledge base.

[INPUT]
langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
..core.config::WikiConfig, WikiCompileConfig (POS: Wiki configuration center)
..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
..core.types::ConceptInfo, WikiArticle, CompileResult, WikiMetadata (POS: Wiki toolkit type definition center)
.queue::WikiIngestionQueue (POS: persistent ingestion queue)

[OUTPUT]
WikiCompiler: LLM-Wiki compilation engine

[POS]
Wiki compilation core engine. Uses LLM to compile raw documents into structured wiki articles:
concept extraction, article generation, index building, and backlink creation. Supports incremental
compilation and SQLite-based persistent controlled batch processing for enterprise-grade reliability.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    import asyncio

    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
import contextlib

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import CompileResult, ConceptInfo, WikiMetadata

from .queue import WikiIngestionQueue

logger = get_agent_logger(__name__)


class WikiCompiler:
    """
    LLM-powered wiki compiler (Karpathy architecture).

    Converts raw documents into structured, interconnected wiki articles.

    Features:
    - Incremental compilation (10x faster, only process new/changed docs)
    - Persistent SQLite queue (prevents OOM and rate limit crashes)
    - Concept extraction and article generation with folder path context
    - Automatic index and Obsidian-compatible backlink generation
    """

    _active_workers: ClassVar[dict[str, asyncio.Task]] = {}

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

    def start_background_worker(self) -> None:
        """Start a background worker to continuously drain the ingestion queue."""
        import asyncio

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
        import asyncio

        user_key = str(self._structure.base_dir)
        consecutive_empty = 0
        try:
            while consecutive_empty < 3:  # Exit after 3 empty checks (15s idle)
                pending_items = self._queue.get_pending_items(limit=5)

                # Auto-retry failed items when no pending work
                if not pending_items:
                    retryable = self._queue.get_retryable_items(max_retries=3, limit=3)
                    if retryable:
                        for item in retryable:
                            self._queue.reset_for_retry(item["id"])
                        logger.info(f"Auto-retrying {len(retryable)} failed items")
                        continue

                    consecutive_empty += 1
                    await asyncio.sleep(5)
                    continue

                consecutive_empty = 0
                logger.info(f"Worker draining {len(pending_items)} items from queue...")

                all_concepts = await self._extract_concepts_batch(pending_items)
                if all_concepts:
                    articles = await self._generate_articles_batch(all_concepts)
                    await self._build_index(all_concepts)
                    if self._config.enable_backlinks:
                        await self._generate_backlinks(all_concepts)
                    await self._save_metadata(len(all_concepts), articles)

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Wiki worker loop failed: {e}")
        finally:
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

        if not pending_items:
            logger.info("No pending files to compile in queue")
            return CompileResult(
                concepts_count=0,
                articles_generated=0,
                backlinks_created=0,
                duration_ms=0,
            )

        logger.info(f"Processing batch of {len(pending_items)} files from queue")

        # Step 1: Extract concepts sequentially from the queue batch
        all_concepts = await self._extract_concepts_batch(pending_items)
        logger.info(f"Extracted {len(all_concepts)} concepts from batch")

        # Step 2: Generate articles for each concept
        articles = await self._generate_articles_batch(all_concepts)
        logger.info(f"Generated {articles} articles")

        # Step 3: Build index
        await self._build_index(all_concepts)

        # Step 4: Generate backlinks
        backlinks_count = 0
        if self._config.enable_backlinks:
            backlinks_count = await self._generate_backlinks(all_concepts)
            logger.info(f"Created {backlinks_count} backlinks")

        # Step 5: Update metadata
        await self._save_metadata(len(all_concepts), articles)

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

        # Start background worker to drain the rest of the queue if any
        self.start_background_worker()

        return CompileResult(
            concepts_count=len(all_concepts),
            articles_generated=articles,
            backlinks_created=backlinks_count,
            duration_ms=duration_ms,
        )

    async def _filter_changed_files(self, raw_files: list[Path]) -> list[Path]:
        """Filter for new or changed files using SHA256 content hashing."""
        metadata_path = self._structure.get_wiki_metadata_path()
        if not metadata_path.exists():
            return raw_files

        try:
            with open(metadata_path, encoding="utf-8") as f:
                metadata = json.load(f)
                known_hashes: dict[str, str] = metadata.get("file_hashes", {})
        except Exception as e:
            logger.warning(f"Failed to read metadata: {e}")
            return raw_files

        changed: list[Path] = []
        for f in raw_files:
            try:
                content_hash = hashlib.sha256(f.read_bytes()).hexdigest()
                if known_hashes.get(str(f)) != content_hash:
                    changed.append(f)
            except OSError:
                changed.append(f)
        return changed

    async def _extract_concepts_batch(self, queue_items: list[dict]) -> list[ConceptInfo]:
        """Extract concepts from queue items sequentially to prevent rate limits."""
        all_concepts: dict[str, ConceptInfo] = {}

        for item in queue_items:
            item_id = item["id"]
            raw_file = Path(item["file_path"])

            self._queue.mark_processing(item_id)

            try:
                if not raw_file.exists():
                    self._queue.mark_failed(item_id, "File not found")
                    continue

                concepts = await self._extract_concepts_from_doc(raw_file)
                for concept in concepts:
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

                self._queue.mark_completed(item_id)
            except Exception as e:
                logger.error(f"Failed to extract concepts from {raw_file}: {e}")
                self._queue.mark_failed(item_id, str(e))

        return list(all_concepts.values())

    async def _extract_concepts_from_doc(self, doc_path: Path) -> list[ConceptInfo]:
        """Extract concepts from a single document using LLM, with path as context."""
        try:
            content = doc_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read {doc_path}: {e}")
            return []

        # Include relative path as context (e.g. docs/architecture.md vs notes/daily.md)
        try:
            relative_path = doc_path.relative_to(self._structure.base_dir)
        except ValueError:
            relative_path = doc_path.name

        prompt = self._compile_config.extract_concepts_prompt_template
        system_msg = SystemMessage(content="You are a knowledge extraction expert.")
        human_msg = HumanMessage(
            content=f"{prompt}\n\n# Document Path: {relative_path}\n# Document Content:\n\n{content}"
        )

        try:
            response = await self._llm.ainvoke([system_msg, human_msg])
            logger.info(f"LLM extraction response for {doc_path}: {response.content}")
            concepts = self._parse_concepts_response(response.content, str(relative_path))
            return concepts
        except Exception as e:
            logger.error(f"LLM extraction failed for {doc_path}: {e}")
            return []

    def _parse_concepts_response(self, response: str, source_file: str) -> list[ConceptInfo]:
        """Parse LLM response into ConceptInfo list (supports JSON and bullet points)."""
        concepts = []
        response_clean = response.strip()

        # Remove markdown code blocks if present
        if response_clean.startswith("```json"):
            response_clean = response_clean[7:]
            if response_clean.endswith("```"):
                response_clean = response_clean[:-3]
            response_clean = response_clean.strip()
        elif response_clean.startswith("```"):
            response_clean = response_clean[3:]
            if response_clean.endswith("```"):
                response_clean = response_clean[:-3]
            response_clean = response_clean.strip()

        try:
            json_data = json.loads(response_clean)
            if isinstance(json_data, list):
                for item in json_data:
                    if isinstance(item, dict) and "name" in item and "definition" in item:
                        raw_related = item.get("related_concepts", [])
                        related = [str(r) for r in raw_related] if isinstance(raw_related, list) else []
                        concepts.append(
                            ConceptInfo(
                                name=item["name"],
                                definition=item["definition"],
                                mentions=1,
                                source_files=[source_file],
                                related_concepts=related,
                            )
                        )
                return concepts
        except (json.JSONDecodeError, KeyError):
            pass

        for line in response_clean.split("\n"):
            line = line.strip()
            # Match formats like: "1. **Concept** - Definition", "- Concept: Definition", "* Concept – Definition"
            match = re.match(r"^(?:\d+\.|\-|\*)\s+(.*?)\s*(?:-|:|–)\s+(.*)", line)
            if match:
                name = match.group(1).replace("**", "").replace("*", "").strip()
                definition = match.group(2).strip()
                if name and definition:
                    concepts.append(
                        ConceptInfo(
                            name=name,
                            definition=definition,
                            mentions=1,
                            source_files=[source_file],
                        )
                    )

        return concepts

    async def _generate_articles_batch(self, concepts: list[ConceptInfo]) -> int:
        """Generate wiki articles for all concepts sequentially."""
        filtered = [c for c in concepts if c.mentions >= self._compile_config.min_concept_mentions]
        logger.info(f"Generating articles for {len(filtered)} concepts")

        success_count = 0
        for concept in filtered:
            try:
                await self._generate_article(concept)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to generate article for {concept.name}: {e}")
        return success_count

    async def _generate_article(self, concept: ConceptInfo) -> None:
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
            article_content = response.content

            if len(article_content) > self._compile_config.max_article_length:
                article_content = article_content[: self._compile_config.max_article_length] + "\n\n(truncated)"

            if self._compile_config.require_approval:
                from .pending import WikiPendingEditsManager

                pending_mgr = WikiPendingEditsManager(self._structure, self._indexer)
                pending_mgr.add_pending_edit(concept.name, article_content)
                logger.info(f"Generated pending draft for article: {concept.name}")
            else:
                article_path = self._structure.get_concept_file_path(concept.name)
                article_path.write_text(article_content, encoding="utf-8")

                # FTS5 and Vector Upsert
                if self._indexer:
                    await self._indexer.upsert(concept.name, article_content)
                    self._indexer.extract_and_upsert_edges(concept.name, article_content)
                else:
                    from ..retrieval.indexer import WikiIndexer

                    indexer = WikiIndexer(self._structure, self._config)
                    await indexer.upsert(concept.name, article_content)
                    indexer.extract_and_upsert_edges(concept.name, article_content)

                logger.info(f"Generated and indexed article: {article_path.name}")

        except Exception as e:
            logger.error(f"Failed to generate article for {concept.name}: {e}")
            raise

    async def _build_index(self, concepts: list[ConceptInfo]) -> None:
        """Build main index file."""
        index_content = "# Wiki Index\n\n"
        index_content += f"*Last updated: {datetime.now(UTC).isoformat()}*\n\n"
        index_content += "## Concepts\n\n"

        for concept in sorted(concepts, key=lambda c: c.name):
            index_content += f"- [[{concept.name}]]\n"

        index_path = self._structure.get_index_file_path()
        index_path.write_text(index_content, encoding="utf-8")
        logger.info(f"Built index: {index_path}")

    async def _generate_backlinks(self, concepts: list[ConceptInfo]) -> int:
        """Generate backlinks between related concepts (Obsidian format)."""
        backlinks_count = 0

        for concept in concepts:
            if not concept.related_concepts:
                continue

            article_path = self._structure.get_concept_file_path(concept.name)
            if not article_path.exists():
                continue

            try:
                content = article_path.read_text(encoding="utf-8")
                # Append related concepts if not already explicitly embedded in the text
                backlinks_section = "\n\n## Related Concepts\n\n"
                for related in concept.related_concepts:
                    # Using Obsidian Wikilinks style
                    backlinks_section += f"- [[{related}]]\n"
                    backlinks_count += 1

                content += backlinks_section
                article_path.write_text(content, encoding="utf-8")

                # Update graph edges for O(1) retrieval
                if self._indexer:
                    self._indexer.extract_and_upsert_edges(concept.name, content)
                else:
                    from ..retrieval.indexer import WikiIndexer

                    indexer = WikiIndexer(self._structure, self._config)
                    indexer.extract_and_upsert_edges(concept.name, content)

            except Exception as e:
                logger.error(f"Failed to add backlinks for {concept.name}: {e}")

        return backlinks_count

    async def _save_metadata(self, concepts_count: int, articles_count: int) -> None:
        """Save wiki metadata including SHA256 file hashes for incremental compilation."""
        raw_files = self._structure.list_raw_files()
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

        metadata_path = self._structure.get_wiki_metadata_path()
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
