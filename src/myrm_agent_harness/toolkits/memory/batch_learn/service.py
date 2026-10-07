"""[POS]: src/myrm_agent_harness/toolkits/memory/batch_learn/service.py
[INPUT]: Chunks, namespacing scopes, and optional processing callables.
[OUTPUT]: BatchMemoryLearningService orchestrating namespaced provenance, resilient execution, and undo.
"""

import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from myrm_agent_harness.toolkits.memory.batch_learn.id_generator import (
    NamespacedIdGenerator,
)
from myrm_agent_harness.toolkits.memory.batch_learn.models import (
    BatchLearnExecutionReport,
    BatchRawChunk,
    ChunkExecutionRecord,
    ChunkProcessingStatus,
    ChunkRetryConfig,
    ItemProvenanceStatus,
    LearnedMemoryItem,
)
from myrm_agent_harness.toolkits.memory.batch_learn.resilient_executor import (
    ResilientChunkRetryExecutor,
)


def _default_chunk_extractor(chunk: BatchRawChunk) -> list[str]:
    """Default heuristic knowledge extractor parsing clean bullet points or sentences."""
    lines = [line.strip().lstrip("-* ").strip() for line in chunk.raw_text.splitlines()]
    return [line for line in lines if len(line) >= 5]


class BatchMemoryLearningService:
    """Core service providing item-level namespaced provenance and resilient chunk batch extraction."""

    def __init__(
        self,
        db_path: str | Path,
        retry_config: ChunkRetryConfig | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.executor = ResilientChunkRetryExecutor(config=retry_config)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS batch_learning_runs (
                    batch_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    sub_scope TEXT NOT NULL,
                    total_chunks INTEGER NOT NULL,
                    successful_chunks INTEGER NOT NULL,
                    retried_chunks INTEGER NOT NULL,
                    failed_chunks INTEGER NOT NULL,
                    total_items INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS batch_learned_items (
                    namespaced_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    layer_recommendation TEXT NOT NULL,
                    provenance_meta_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(batch_id) REFERENCES batch_learning_runs(batch_id)
                );

                CREATE TABLE IF NOT EXISTS batch_chunk_diagnostics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    elapsed_ms REAL NOT NULL,
                    error_message TEXT,
                    extracted_count INTEGER NOT NULL,
                    FOREIGN KEY(batch_id) REFERENCES batch_learning_runs(batch_id)
                );
            """)
            conn.commit()

    def learn_batch(
        self,
        chunks: list[BatchRawChunk],
        scope: str = "default",
        sub_scope: str = "global",
        category: str = "general",
        custom_processor: Callable[[BatchRawChunk], list[str]] | None = None,
    ) -> BatchLearnExecutionReport:
        """Process multiple raw chunks resiliently and persist items with deterministic namespaced IDs."""
        batch_id = f"batch_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        processor = custom_processor or _default_chunk_extractor

        chunk_diagnostics: list[ChunkExecutionRecord] = []
        all_learned_items: list[LearnedMemoryItem] = []

        success_count = 0
        retried_count = 0
        failed_count = 0

        for chunk in chunks:
            raw_memories, record = self.executor.execute_chunk(chunk, processor)
            chunk_diagnostics.append(record)

            if record.status == ChunkProcessingStatus.SUCCESS:
                success_count += 1
            elif record.status == ChunkProcessingStatus.RETRIED_SUCCESS:
                retried_count += 1
            else:
                failed_count += 1

            for memory_text in raw_memories:
                ns_id = NamespacedIdGenerator.generate(
                    scope=scope,
                    sub_scope=sub_scope,
                    category=category,
                    content=memory_text,
                )
                item = LearnedMemoryItem(
                    namespaced_id=ns_id.full_id,
                    batch_id=batch_id,
                    chunk_index=chunk.chunk_index,
                    content=memory_text,
                    tags=[category, scope],
                    layer_recommendation="semantic",
                    provenance_meta={
                        "scope": scope,
                        "sub_scope": sub_scope,
                        "category": category,
                        "chunk_index": chunk.chunk_index,
                    },
                    status=ItemProvenanceStatus.ACTIVE,
                    created_at=time.time(),
                )
                all_learned_items.append(item)

        # Persist to database
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO batch_learning_runs (
                    batch_id, scope, sub_scope, total_chunks,
                    successful_chunks, retried_chunks, failed_chunks,
                    total_items, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    scope,
                    sub_scope,
                    len(chunks),
                    success_count,
                    retried_count,
                    failed_count,
                    len(all_learned_items),
                    time.time(),
                ),
            )

            for diag in chunk_diagnostics:
                conn.execute(
                    """
                    INSERT INTO batch_chunk_diagnostics (
                        batch_id, chunk_index, status, attempt_count,
                        elapsed_ms, error_message, extracted_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        diag.chunk_index,
                        diag.status.value,
                        diag.attempt_count,
                        diag.elapsed_ms,
                        diag.error_message,
                        diag.extracted_items_count,
                    ),
                )

            for item in all_learned_items:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO batch_learned_items (
                        namespaced_id, batch_id, chunk_index, content,
                        tags_json, layer_recommendation, provenance_meta_json,
                        status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.namespaced_id,
                        item.batch_id,
                        item.chunk_index,
                        item.content,
                        json.dumps(item.tags, ensure_ascii=False),
                        item.layer_recommendation,
                        json.dumps(item.provenance_meta, ensure_ascii=False),
                        item.status.value,
                        item.created_at,
                    ),
                )
            conn.commit()

        return BatchLearnExecutionReport(
            batch_id=batch_id,
            total_chunks=len(chunks),
            successful_chunks=success_count,
            retried_chunks=retried_count,
            failed_chunks=failed_count,
            total_items_learned=len(all_learned_items),
            chunk_diagnostics=chunk_diagnostics,
            items=all_learned_items,
        )

    def get_item_by_namespaced_id(self, namespaced_id: str) -> LearnedMemoryItem | None:
        """Retrieve a specific learned item by its unique namespaced ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM batch_learned_items WHERE namespaced_id = ?",
                (namespaced_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return LearnedMemoryItem(
                namespaced_id=str(row["namespaced_id"]),
                batch_id=str(row["batch_id"]),
                chunk_index=int(row["chunk_index"]),
                content=str(row["content"]),
                tags=json.loads(row["tags_json"]),
                layer_recommendation=str(row["layer_recommendation"]),
                provenance_meta=json.loads(row["provenance_meta_json"]),
                status=ItemProvenanceStatus(row["status"]),
                created_at=float(row["created_at"]),
            )

    def undo_item_by_namespaced_id(self, namespaced_id: str) -> bool:
        """Mark a specific learned memory item as revoked in the audit ledger."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE batch_learned_items
                SET status = ?
                WHERE namespaced_id = ? AND status != ?
                """,
                (
                    ItemProvenanceStatus.REVOKED.value,
                    namespaced_id,
                    ItemProvenanceStatus.REVOKED.value,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_items_by_batch(self, batch_id: str) -> list[LearnedMemoryItem]:
        """Fetch all memory items produced within a batch."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM batch_learned_items WHERE batch_id = ? ORDER BY chunk_index ASC",
                (batch_id,),
            )
            items: list[LearnedMemoryItem] = []
            for row in cursor.fetchall():
                items.append(
                    LearnedMemoryItem(
                        namespaced_id=str(row["namespaced_id"]),
                        batch_id=str(row["batch_id"]),
                        chunk_index=int(row["chunk_index"]),
                        content=str(row["content"]),
                        tags=json.loads(row["tags_json"]),
                        layer_recommendation=str(row["layer_recommendation"]),
                        provenance_meta=json.loads(row["provenance_meta_json"]),
                        status=ItemProvenanceStatus(row["status"]),
                        created_at=float(row["created_at"]),
                    )
                )
            return items

    def close(self) -> None:
        """Placeholder for clean database lifecycle maintenance."""
