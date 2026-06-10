"""Plan Archive & Recall — historical plan storage and retrieval for cold-start mitigation.

Stores successfully completed plans and retrieves similar ones as few-shot references
for future planning tasks, enabling PlannerAgent to learn from past successes.

[INPUT]
- toolkits.memory.protocols.vector::VectorStoreProtocol (POS: Vector store protocol for memory system.)
- toolkits.memory.protocols.embedding::EmbeddingProtocol (POS: Protocol for text embedding models.)

[OUTPUT]
- PlanArchiveStore: SQLite + Qdrant dual persistence for plan archives.
- PlanRecaller: Vector search based plan retrieval with quality filtering.

[POS]
Plan Archive & Recall for PlannerAgent cold-start mitigation.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS plan_archive (
    plan_id         TEXT PRIMARY KEY,
    goal            TEXT NOT NULL,
    reasoning       TEXT NOT NULL DEFAULT '',
    steps_summary   TEXT NOT NULL,
    step_count      INTEGER NOT NULL,
    success_rate    REAL NOT NULL DEFAULT 1.0,
    error_patterns  TEXT NOT NULL DEFAULT '',
    key_decisions   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    user_id         TEXT NOT NULL DEFAULT '',
    agent_id        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_archive_goal ON plan_archive(goal);
CREATE INDEX IF NOT EXISTS idx_archive_user ON plan_archive(user_id);
CREATE INDEX IF NOT EXISTS idx_archive_created ON plan_archive(created_at);
"""

VECTOR_COLLECTION = "plan_archive"
SIMILARITY_THRESHOLD = 0.75
DEDUP_THRESHOLD = 0.95
MIN_SUCCESS_RATE = 0.8


def _build_embed_text(goal: str, steps_summary: str) -> str:
    """Build embedding text from goal and steps."""
    return f"{goal}\n{steps_summary}"


def _build_recall_text(
    goal: str,
    steps_summary: str,
    error_patterns: str,
    key_decisions: str,
) -> str:
    """Build concise recall text for few-shot injection (budget-aware)."""
    lines = [f"Goal: {goal}", f"Steps: {steps_summary}"]
    if error_patterns:
        lines.append(f"Error Recovery: {error_patterns}")
    if key_decisions:
        lines.append(f"Key Decisions: {key_decisions}")
    return "\n".join(lines)


class PlanArchiveStore:
    """SQLite + Qdrant dual persistence for plan archives.

    Stores completed plans with quality metrics for future recall.
    Thread-safe via WAL mode and asyncio.to_thread for blocking I/O.
    """

    def __init__(
        self,
        db_path: Path,
        vector_store: VectorStoreProtocol | None = None,
        embedding: EmbeddingProtocol | None = None,
    ) -> None:
        self._db_path = db_path
        self._vector_store = vector_store
        self._embedding = embedding
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._writer() as conn:
            conn.executescript(_DDL)

    @contextmanager
    def _writer(self):
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _reader(self):
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    async def archive_plan(
        self,
        plan: Plan,
        user_id: str = "",
        agent_id: str = "",
    ) -> bool:
        """Archive a successfully completed plan.

        Returns True if archived, False if skipped (dedup or quality gate).
        """
        success_rate = self._compute_success_rate(plan)
        if success_rate < MIN_SUCCESS_RATE:
            logger.info("Plan archive skipped: success_rate %.2f < %.2f", success_rate, MIN_SUCCESS_RATE)
            return False

        steps_summary = " → ".join(s.description[:60] for s in plan.steps[:8])
        error_patterns = self._extract_error_patterns(plan)
        key_decisions = self._extract_key_decisions(plan)

        if await self._is_duplicate(plan.goal, steps_summary):
            logger.info("Plan archive skipped: duplicate detected for goal '%s'", plan.goal[:50])
            return False

        plan_id = f"plan_{int(time.time() * 1000)}"
        now = datetime.now().isoformat()

        def _write() -> None:
            with self._writer() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO plan_archive
                    (plan_id, goal, reasoning, steps_summary, step_count, success_rate,
                     error_patterns, key_decisions, created_at, user_id, agent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        plan_id,
                        plan.goal,
                        plan.reasoning,
                        steps_summary,
                        len(plan.steps),
                        success_rate,
                        error_patterns,
                        key_decisions,
                        now,
                        user_id,
                        agent_id,
                    ),
                )

        await asyncio.to_thread(_write)
        await self._sync_to_vector(plan_id, plan.goal, steps_summary)
        logger.info("Plan archived: %s (goal: %s)", plan_id, plan.goal[:50])
        return True

    async def _is_duplicate(self, goal: str, steps_summary: str) -> bool:
        """Check if a very similar plan already exists via vector similarity."""
        if not self._vector_store or not self._embedding:
            return False
        try:
            text = _build_embed_text(goal, steps_summary)
            vector = await self._embedding.embed(text)
            results = await self._vector_store.search(
                VECTOR_COLLECTION, vector, limit=1, score_threshold=DEDUP_THRESHOLD
            )
            if results:
                return True
        except Exception as e:
            logger.warning("Dedup check failed (proceeding with archive): %s", e)
        return False

    async def _sync_to_vector(self, plan_id: str, goal: str, steps_summary: str) -> None:
        """Upsert plan embedding to vector store."""
        if not self._vector_store or not self._embedding:
            return
        try:
            from myrm_agent_harness.toolkits.vector.base import VectorDocument

            text = _build_embed_text(goal, steps_summary)
            vector = await self._embedding.embed(text)
            doc = VectorDocument(
                id=plan_id,
                content=text,
                vector=vector,
                metadata={"plan_id": plan_id},
            )
            await self._vector_store.upsert(VECTOR_COLLECTION, [doc])
        except Exception as e:
            logger.warning("Vector sync failed for plan %s: %s", plan_id, e)

    @staticmethod
    def _compute_success_rate(plan: Plan) -> float:
        """Compute plan success rate from step statuses."""
        if not plan.steps:
            return 0.0
        completed = sum(1 for s in plan.steps if s.status == "completed")
        return completed / len(plan.steps)

    @staticmethod
    def _extract_error_patterns(plan: Plan) -> str:
        """Extract concise error recovery patterns from plan."""
        if not plan.errors_encountered:
            return ""
        patterns = []
        for err in plan.errors_encountered[:3]:
            if err.resolution and err.resolution_success:
                patterns.append(f"{err.error_type}: {err.resolution[:80]}")
        return "; ".join(patterns)

    @staticmethod
    def _extract_key_decisions(plan: Plan) -> str:
        """Extract key architectural decisions."""
        if not plan.decisions:
            return ""
        active = [d for d in plan.decisions if d.status == "active"]
        return "; ".join(f"{d.topic}: {d.decision[:60]}" for d in active[:3])


class PlanRecaller:
    """Vector search based plan retrieval with quality filtering.

    Retrieves similar historical plans as few-shot references for PlannerAgent.
    """

    def __init__(self, archive_store: PlanArchiveStore) -> None:
        self._store = archive_store

    async def recall(
        self,
        task_description: str,
        user_id: str = "",
        limit: int = 2,
    ) -> str:
        """Recall similar historical plans as formatted few-shot text.

        Returns empty string if no relevant plans found (graceful degradation).
        """
        if not self._store._vector_store or not self._store._embedding:
            return await self._fallback_recall(task_description, user_id, limit)

        try:
            vector = await self._store._embedding.embed(task_description)
            results = await self._store._vector_store.search(
                VECTOR_COLLECTION, vector, limit=limit * 3, score_threshold=SIMILARITY_THRESHOLD
            )

            if not results:
                return ""

            plan_ids = [r.document.id for r in results][:limit]

            if not plan_ids:
                return ""

            return await self._fetch_and_format(plan_ids)
        except Exception as e:
            logger.warning("Plan recall via vector failed, trying fallback: %s", e)
            return await self._fallback_recall(task_description, user_id, limit)

    async def _fallback_recall(
        self, task_description: str, user_id: str, limit: int
    ) -> str:
        """SQLite LIKE fallback when vector search is unavailable."""
        keywords = task_description[:100].split()[:3]
        if not keywords:
            return ""

        def _search() -> list[str]:
            with self._store._reader() as conn:
                conditions = " OR ".join(["goal LIKE ?"] * len(keywords))
                params = [f"%{kw}%" for kw in keywords]
                if user_id:
                    sql = f"""SELECT plan_id FROM plan_archive
                              WHERE ({conditions}) AND user_id = ?
                              ORDER BY created_at DESC LIMIT ?"""
                    params.extend([user_id, limit])
                else:
                    sql = f"""SELECT plan_id FROM plan_archive
                              WHERE ({conditions})
                              ORDER BY created_at DESC LIMIT ?"""
                    params.append(limit)
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [row["plan_id"] for row in rows]

        try:
            plan_ids = await asyncio.to_thread(_search)
            if not plan_ids:
                return ""
            return await self._fetch_and_format(plan_ids)
        except Exception as e:
            logger.warning("Plan recall fallback failed: %s", e)
            return ""

    async def _fetch_and_format(self, plan_ids: list[str]) -> str:
        """Fetch plans from SQLite and format as concise few-shot text."""

        def _fetch() -> list[dict]:
            with self._store._reader() as conn:
                placeholders = ",".join("?" * len(plan_ids))
                rows = conn.execute(
                    f"SELECT * FROM plan_archive WHERE plan_id IN ({placeholders})",
                    tuple(plan_ids),
                ).fetchall()
                return [dict(row) for row in rows]

        records = await asyncio.to_thread(_fetch)
        if not records:
            return ""

        sections = []
        for rec in records:
            text = _build_recall_text(
                rec["goal"],
                rec["steps_summary"],
                rec["error_patterns"],
                rec["key_decisions"],
            )
            sections.append(text)

        header = "## Reference Plans (from similar past tasks)\n"
        body = "\n---\n".join(sections)
        return header + body


__all__ = ["PlanArchiveStore", "PlanRecaller"]
