"""Indexing engine for local file search.

[INPUT]
- .config::LocalFileSearchConfig, SUPPORTED_EXTENSIONS, VECTOR_COLLECTION_NAME (POS: configuration and constants)
- .models::FileRecord, IndexStats, IndexStatus, IndexedDirectory (POS: data models)
- myrm_agent_harness.toolkits.file_parsers (POS: multi-format file parsing)
- myrm_agent_harness.toolkits.retriever.embedding (POS: text embedding service)
- myrm_agent_harness.toolkits.retriever.splitter (POS: text chunking)
- myrm_agent_harness.toolkits.vector.base (POS: vector store abstraction)

[OUTPUT]
- LocalFileIndexer: Async indexing engine with SHA256 incremental updates

[POS]
Core indexing engine. Scans configured directories, parses supported file formats,
chunks text, embeds and stores vectors. Uses SHA256 content hashing for incremental
updates — only re-indexes changed files.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.local_file_search.config import (
    SUPPORTED_EXTENSIONS,
    VECTOR_COLLECTION_NAME,
    LocalFileSearchConfig,
)
from myrm_agent_harness.toolkits.local_file_search.models import (
    FileRecord,
    IndexedDirectory,
    IndexStats,
    IndexStatus,
)
from myrm_agent_harness.toolkits.retriever.embedding import EmbeddingService
from myrm_agent_harness.toolkits.retriever.splitter import TextChunker
from myrm_agent_harness.toolkits.vector.base import VectorDocument, VectorStore

logger = logging.getLogger(__name__)

_BATCH_UPSERT_SIZE = 100
_MAX_CONSECUTIVE_FAILURES = 5


def _compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash of file content, reading in 64KB blocks for efficiency."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _scan_directory(
    directory: IndexedDirectory,
    exclude_set: frozenset[str],
    max_file_size: int,
) -> list[str]:
    """Scan a directory for indexable files. Returns absolute paths."""
    root = Path(directory.path)
    if not root.is_dir():
        logger.warning("Directory does not exist or is not a directory: %s", directory.path)
        return []

    result: list[str] = []
    for current_root, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if d not in exclude_set and not d.startswith(".")
        ]
        if not directory.recursive and current_root != str(root):
            dirnames.clear()
            continue

        for filename in filenames:
            if filename.startswith("."):
                continue
            ext = Path(filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            full_path = os.path.join(current_root, filename)
            try:
                if os.path.getsize(full_path) > max_file_size:
                    continue
            except OSError:
                continue
            result.append(full_path)
    return result


_RICH_PARSEABLE_EXTENSIONS = frozenset({".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"})


async def _parse_file_content(file_path: str) -> str | None:
    """Parse file content using the file_parsers toolkit. Returns None on failure."""
    ext = Path(file_path).suffix.lower()

    try:
        if ext in _RICH_PARSEABLE_EXTENSIONS:
            from myrm_agent_harness.toolkits.file_parsers import get_parser

            parser = get_parser(file_path)
            content = await parser.parse(file_path)
            return content if content and content.strip() else None

        if ext in SUPPORTED_EXTENSIONS:
            loop = asyncio.get_running_loop()
            content = await loop.run_in_executor(
                None,
                lambda: Path(file_path).read_text(encoding="utf-8", errors="replace"),
            )
            return content if content and content.strip() else None

    except Exception as e:
        logger.warning("Failed to parse file %s: %s", file_path, e)

    return None


class LocalFileIndexer:
    """Async indexing engine for local files.

    Workflow:
    1. Scan configured directories for supported files
    2. Compute SHA256 hashes, skip unchanged files (incremental)
    3. Parse file content via file_parsers toolkit
    4. Chunk text via retriever splitter
    5. Embed chunks and store in vector DB

    Thread safety: single indexing task at a time via asyncio.Lock.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
        config: LocalFileSearchConfig,
        embedding_dimension: int = 1536,
    ):
        self._store = vector_store
        self._embeddings = embedding_service
        self._config = config
        self._embedding_dimension = embedding_dimension
        self._chunker = TextChunker()
        self._file_records: dict[str, FileRecord] = {}
        self._stats = IndexStats()
        self._lock = asyncio.Lock()

    @property
    def stats(self) -> IndexStats:
        return self._stats

    @property
    def file_records(self) -> dict[str, FileRecord]:
        return dict(self._file_records)

    def restore_records(self, records: list[FileRecord]) -> None:
        """Restore file records from persistence (called by business layer on startup)."""
        self._file_records = {r.path: r for r in records}
        self._stats.total_files = len(self._file_records)
        self._stats.total_chunks = sum(r.chunk_count for r in records)

    async def ensure_collection(self) -> None:
        """Create or recreate the vector collection with correct dimensions."""
        exists = await self._store.collection_exists(VECTOR_COLLECTION_NAME)
        if exists:
            info = await self._store.get_collection_info(VECTOR_COLLECTION_NAME)
            if info and info.dimension != self._embedding_dimension:
                logger.warning(
                    "Collection %s dimension mismatch: expected=%d, actual=%d. Recreating.",
                    VECTOR_COLLECTION_NAME,
                    self._embedding_dimension,
                    info.dimension,
                )
                await self._store.delete_collection(VECTOR_COLLECTION_NAME)
                exists = False
        if not exists:
            await self._store.create_collection(
                VECTOR_COLLECTION_NAME,
                dimension=self._embedding_dimension,
            )
            logger.info("Created vector collection: %s (dim=%d)", VECTOR_COLLECTION_NAME, self._embedding_dimension)

    async def index_all(self) -> IndexStats:
        """Run a full incremental index across all enabled directories.

        Returns updated IndexStats. Only one indexing task runs at a time.
        """
        if self._lock.locked():
            logger.warning("Indexing already in progress, skipping")
            return self._stats

        async with self._lock:
            return await self._do_index()

    async def _do_index(self) -> IndexStats:
        """Core indexing logic — must be called under self._lock."""
        start_time = time.perf_counter()
        self._stats.status = IndexStatus.INDEXING
        self._stats.indexing_progress = 0.0
        self._stats.error_count = 0

        enabled_dirs = self._config.get_enabled_directories()
        exclude_set = self._config.get_exclude_set()

        if not enabled_dirs:
            logger.info("No enabled directories configured for indexing")
            self._stats.status = IndexStatus.IDLE
            return self._stats

        self._stats.total_directories = len(enabled_dirs)

        all_files: list[tuple[str, IndexedDirectory]] = []
        for dir_cfg in enabled_dirs:
            paths = _scan_directory(dir_cfg, exclude_set, self._config.max_file_size_bytes)
            all_files.extend((p, dir_cfg) for p in paths)

        total = len(all_files)
        logger.info("Scan complete: %d files across %d directories", total, len(enabled_dirs))

        if total == 0:
            if self._file_records:
                await self._remove_stale_files(set(self._file_records.keys()))
                self._stats.total_files = 0
                self._stats.total_chunks = 0
            self._stats.status = IndexStatus.IDLE
            self._stats.indexing_progress = 1.0
            return self._stats

        await self.ensure_collection()

        current_paths: set[str] = set()
        indexed_count = 0
        consecutive_failures = 0

        for i, (file_path, dir_cfg) in enumerate(all_files):
            current_paths.add(file_path)
            self._stats.current_file = file_path
            self._stats.indexing_progress = i / total

            try:
                file_hash = await asyncio.get_running_loop().run_in_executor(
                    None, _compute_file_hash, file_path
                )
            except OSError as e:
                logger.warning("Cannot hash file %s: %s", file_path, e)
                self._stats.error_count += 1
                continue

            existing = self._file_records.get(file_path)
            if existing and existing.content_hash == file_hash:
                continue

            success = await self._index_single_file(file_path, file_hash, dir_cfg)
            if success:
                indexed_count += 1
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "Aborting indexing: %d consecutive failures (embedding service may be down)",
                        consecutive_failures,
                    )
                    self._stats.status = IndexStatus.FAILED
                    break

        stale_paths = set(self._file_records.keys()) - current_paths
        if stale_paths:
            await self._remove_stale_files(stale_paths)
            logger.info("Removed %d stale file records", len(stale_paths))

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if self._stats.status != IndexStatus.FAILED:
            self._stats.status = IndexStatus.IDLE
        self._stats.indexing_progress = 1.0
        self._stats.current_file = None
        self._stats.last_indexed_at = datetime.now(UTC)
        self._stats.total_files = len(self._file_records)
        self._stats.total_chunks = sum(r.chunk_count for r in self._file_records.values())

        logger.info(
            "Indexing complete: indexed=%d, total_files=%d, total_chunks=%d, "
            "errors=%d, elapsed=%.0fms",
            indexed_count,
            self._stats.total_files,
            self._stats.total_chunks,
            self._stats.error_count,
            elapsed_ms,
        )
        return self._stats

    async def _index_single_file(
        self,
        file_path: str,
        file_hash: str,
        dir_cfg: IndexedDirectory,
    ) -> bool:
        """Parse, chunk, embed, and store a single file. Returns True on success."""
        content = await _parse_file_content(file_path)
        if not content:
            self._stats.error_count += 1
            return False

        ext = Path(file_path).suffix.lower().lstrip(".")
        try:
            rel_path = str(Path(file_path).relative_to(dir_cfg.path))
        except ValueError:
            rel_path = Path(file_path).name

        chunks = self._chunker.chunk_text(
            content,
            document_metadata={"file_path": file_path, "file_type": ext},
        )

        if not chunks:
            logger.warning("No chunks produced for file: %s", file_path)
            return False

        existing = self._file_records.get(file_path)
        if existing:
            await self._store.delete_by_filter(
                VECTOR_COLLECTION_NAME,
                {"source_path": file_path},
            )

        vector_docs: list[VectorDocument] = []
        texts = [c.page_content for c in chunks]

        try:
            vectors = await self._embeddings.embed_batch(texts)
        except Exception as e:
            logger.error("Embedding failed for %s: %s", file_path, e)
            self._stats.error_count += 1
            return False

        for idx, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            section = chunk.metadata.get("section", "")
            doc = VectorDocument(
                content=chunk.page_content,
                vector=vector,
                metadata={
                    "source_path": file_path,
                    "relative_path": rel_path,
                    "directory_id": dir_cfg.id,
                    "file_type": ext,
                    "chunk_index": idx,
                    "section": section,
                },
            )
            vector_docs.append(doc)

        for batch_start in range(0, len(vector_docs), _BATCH_UPSERT_SIZE):
            batch = vector_docs[batch_start : batch_start + _BATCH_UPSERT_SIZE]
            await self._store.upsert(VECTOR_COLLECTION_NAME, batch)

        record = FileRecord(
            path=file_path,
            relative_path=rel_path,
            directory_id=dir_cfg.id,
            content_hash=file_hash,
            file_size=os.path.getsize(file_path),
            file_type=ext,
            chunk_count=len(vector_docs),
        )
        self._file_records[file_path] = record

        logger.info("Indexed: %s (%d chunks)", rel_path, len(vector_docs))
        return True

    async def _remove_stale_files(self, stale_paths: set[str]) -> None:
        """Remove vector records for files that no longer exist."""
        for path in stale_paths:
            try:
                await self._store.delete_by_filter(
                    VECTOR_COLLECTION_NAME,
                    {"source_path": path},
                )
            except Exception as e:
                logger.warning("Failed to delete vectors for stale file %s: %s", path, e)
            self._file_records.pop(path, None)

    async def remove_directory(self, directory_id: str) -> int:
        """Remove all indexed files for a specific directory. Returns files removed."""
        paths_to_remove = [
            path for path, rec in self._file_records.items()
            if rec.directory_id == directory_id
        ]
        for path in paths_to_remove:
            try:
                await self._store.delete_by_filter(
                    VECTOR_COLLECTION_NAME,
                    {"source_path": path},
                )
            except Exception as e:
                logger.warning("Failed to delete vectors for %s: %s", path, e)
            self._file_records.pop(path, None)

        self._stats.total_files = len(self._file_records)
        self._stats.total_chunks = sum(r.chunk_count for r in self._file_records.values())
        return len(paths_to_remove)
