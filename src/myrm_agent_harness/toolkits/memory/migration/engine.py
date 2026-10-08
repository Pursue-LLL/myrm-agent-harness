"""Multi-platform memory migration execution pipeline engine.

[POS]
Orchestrates heterogeneous document ingestion, security validation, multi-tier deduplication,
sliding-window semantic chunking, and dual FTS/Vector ingestion with graceful fallback.

[INPUT]
- asyncio, collections.abc.Callable, collections.abc.Awaitable
- pathlib.Path, time, uuid
- .models (ChunkedMemoryArtifact, ExtractedMemoryUnit, MigrationRunReport, MigrationSecurityPolicy, MigrationSourceType)
- .security_guard.MigrationSecurityGuard
- .parsers.MultiPlatformParserMatrix
- .deduplicator.MigrationDeduplicator
- myrm_agent_harness.toolkits.memory.chunking (ChunkingConfig, MarkdownSlidingWindowChunker)

[OUTPUT]
- MultiPlatformMigrationEngine, VectorSinkFunc, FtsSinkFunc
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from myrm_agent_harness.toolkits.memory.chunking import (
    ChunkingConfig,
    MarkdownSlidingWindowChunker,
)
from myrm_agent_harness.toolkits.memory.migration.deduplicator import (
    MigrationDeduplicator,
)
from myrm_agent_harness.toolkits.memory.migration.models import (
    ChunkedMemoryArtifact,
    ExtractedMemoryUnit,
    MigrationRunReport,
    MigrationSecurityPolicy,
    MigrationSourceType,
)
from myrm_agent_harness.toolkits.memory.migration.parsers import (
    MultiPlatformParserMatrix,
)
from myrm_agent_harness.toolkits.memory.migration.security_guard import (
    MigrationSecurityGuard,
)

VectorSinkFunc = Callable[[list[ChunkedMemoryArtifact]], Awaitable[bool]]
FtsSinkFunc = Callable[[list[ExtractedMemoryUnit]], Awaitable[bool]]


class MultiPlatformMigrationEngine:
    """Core execution engine orchestrating safe, deduplicated, and chunked memory migrations."""

    def __init__(
        self,
        security_policy: MigrationSecurityPolicy | None = None,
        chunking_config: ChunkingConfig | None = None,
        vector_sink: VectorSinkFunc | None = None,
        fts_sink: FtsSinkFunc | None = None,
        vector_timeout_seconds: float = 3.0,
    ) -> None:
        self._guard = MigrationSecurityGuard(policy=security_policy)
        self._parser_matrix = MultiPlatformParserMatrix(security_guard=self._guard)
        self._deduplicator = MigrationDeduplicator()
        self._chunker = MarkdownSlidingWindowChunker(config=chunking_config or ChunkingConfig())
        self._vector_sink = vector_sink
        self._fts_sink = fts_sink
        self._vector_timeout = vector_timeout_seconds

    @property
    def deduplicator(self) -> MigrationDeduplicator:
        return self._deduplicator

    async def migrate_file(
        self,
        source_type: MigrationSourceType,
        file_path: Path | str,
    ) -> tuple[list[ExtractedMemoryUnit], MigrationRunReport]:
        """Execute migration for a single external document file."""
        path = Path(file_path)
        start_time = time.perf_counter()
        migration_id = f"mig-{uuid.uuid4().hex[:10]}"

        if not path.is_file():
            report = self._build_empty_report(migration_id, source_type, str(path), start_time)
            return [], report

        # Level 1 fast deduplication check
        if self._deduplicator.is_file_unchanged(path):
            report = self._build_empty_report(
                migration_id, source_type, str(path), start_time, skipped=1
            )
            return [], report

        # Security check & parse
        units = self._parser_matrix.parse_file(source_type, path)
        admitted, chunks, vec_status = await self._process_units(units)

        # Record file metadata for Level 1 deduplication
        self._deduplicator.record_file_seen(path)

        total_latency = (time.perf_counter() - start_time) * 1000.0
        report = MigrationRunReport(
            migration_id=migration_id,
            source_type=source_type,
            source_path=str(path),
            total_scanned=len(units),
            total_admitted=len(admitted),
            total_skipped_duplicates=len(units) - len(admitted),
            total_chunks_generated=len(chunks),
            vector_ingestion_status=vec_status,
            latency_ms=round(total_latency, 2),
            timestamp=time.time(),
        )
        return admitted, report

    async def migrate_payload(
        self,
        source_type: MigrationSourceType,
        raw_content: str,
        source_label: str = "raw_buffer",
    ) -> tuple[list[ExtractedMemoryUnit], MigrationRunReport]:
        """Execute migration for in-memory text payload."""
        start_time = time.perf_counter()
        migration_id = f"mig-{uuid.uuid4().hex[:10]}"

        # Security check batch size
        self._guard.validate_batch(len(raw_content.encode("utf-8")))

        units = self._parser_matrix.parse_payload(
            source_type=source_type,
            raw_content=raw_content,
            source_id=source_label,
        )
        admitted, chunks, vec_status = await self._process_units(units)

        total_latency = (time.perf_counter() - start_time) * 1000.0
        report = MigrationRunReport(
            migration_id=migration_id,
            source_type=source_type,
            source_path=f"memory://{source_label}",
            total_scanned=len(units),
            total_admitted=len(admitted),
            total_skipped_duplicates=len(units) - len(admitted),
            total_chunks_generated=len(chunks),
            vector_ingestion_status=vec_status,
            latency_ms=round(total_latency, 2),
            timestamp=time.time(),
        )
        return admitted, report

    async def _process_units(
        self, units: list[ExtractedMemoryUnit]
    ) -> tuple[list[ExtractedMemoryUnit], list[ChunkedMemoryArtifact], str]:
        """Deduplicate, chunk, and sink units with graceful vector fallback."""
        if not units:
            return [], [], "skipped_no_items"

        # Level 2 & 3 deduplication
        dedup_res = self._deduplicator.filter_units(units)
        admitted = dedup_res.admitted_units

        if not admitted:
            return [], [], "skipped_all_duplicates"

        # Sliding window chunking (linked to 132-suite)
        chunked_artifacts = self._generate_chunks(admitted)

        # FTS sink (guaranteed keyword baseline)
        if self._fts_sink is not None:
            with contextlib.suppress(Exception):
                await self._fts_sink(admitted)

        # Vector sink with graceful fallback (linked to 133-suite resilience)
        vec_status = "success"
        if self._vector_sink is not None:
            try:
                await asyncio.wait_for(
                    self._vector_sink(chunked_artifacts),
                    timeout=self._vector_timeout,
                )
            except (TimeoutError, Exception):
                vec_status = "fallback_fts_only"
        else:
            vec_status = "skipped_no_provider"

        return admitted, chunked_artifacts, vec_status

    def _generate_chunks(
        self, units: list[ExtractedMemoryUnit]
    ) -> list[ChunkedMemoryArtifact]:
        """Apply sliding-window chunker to long memory facts."""
        artifacts: list[ChunkedMemoryArtifact] = []
        for unit in units:
            text = unit.normalized_text
            # If text is long enough, split with sliding window
            if len(text) > 300:
                chunks = self._chunker.chunk_document(
                    source_path=unit.source_id,
                    content=text,
                )
                for c in chunks:
                    artifacts.append(
                        ChunkedMemoryArtifact(
                            unit_id=unit.source_id,
                            layer=unit.layer,
                            chunk_id=c.chunk_id,
                            text=c.text,
                            chunk_hash=c.chunk_hash,
                            start_line=c.start_line,
                            end_line=c.end_line,
                            token_estimate=c.token_estimate,
                        )
                    )
            else:
                # Single atomic chunk
                artifacts.append(
                    ChunkedMemoryArtifact(
                        unit_id=unit.source_id,
                        layer=unit.layer,
                        chunk_id=f"{unit.source_id}_c0",
                        text=text,
                        chunk_hash=unit.content_hash,
                        start_line=1,
                        end_line=1,
                        token_estimate=len(text) // 4,
                    )
                )
        return artifacts

    def _build_empty_report(
        self,
        migration_id: str,
        source_type: MigrationSourceType,
        source_path: str,
        start_time: float,
        skipped: int = 0,
    ) -> MigrationRunReport:
        latency = (time.perf_counter() - start_time) * 1000.0
        return MigrationRunReport(
            migration_id=migration_id,
            source_type=source_type,
            source_path=source_path,
            total_scanned=0,
            total_admitted=0,
            total_skipped_duplicates=skipped,
            total_chunks_generated=0,
            vector_ingestion_status="skipped_unchanged" if skipped else "skipped_not_found",
            latency_ms=round(latency, 2),
            timestamp=time.time(),
        )
