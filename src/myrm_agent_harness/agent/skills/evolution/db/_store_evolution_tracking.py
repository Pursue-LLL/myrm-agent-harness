"""Evolution tracking persistence for skill evolution system.

Handles CRUD operations for the evolution rejections and evolution constraints tables.

[INPUT]
- (none)

[OUTPUT]
- SkillEvolutionTrackingMixin: Mixin providing evolution tracking persistence for SkillStore.

[POS]
Evolution tracking persistence (rejections, constraints) for skill evolution system.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from datetime import UTC

logger = logging.getLogger(__name__)

__all__ = ["SkillEvolutionTrackingMixin"]


class SkillEvolutionTrackingMixin:
    """Mixin providing evolution tracking persistence for SkillStore.

    Expects host class to have:
    - _mu: threading.Lock
    - _conn: sqlite3.Connection
    - _ensure_open(): None
    - _reader(): context manager yielding sqlite3.Connection
    - _db_retry decorator on the class (applied at host level)
    """

    _mu: threading.Lock
    _conn: sqlite3.Connection

    # --- Evolution rejection tracking ---

    def _save_rejection_sync(
        self,
        skill_id: str,
        trigger_type: str,
        proposed_type: str,
        rejection_reason: str,
        confidence: float,
        trigger_context: str,
        rejected_at_iso: str,
    ) -> None:
        """Synchronous rejection save."""
        with self._mu:
            self._conn.execute(
                """
                INSERT INTO evolution_rejections (
                    skill_id, trigger_type, proposed_type, rejection_reason,
                    confidence, trigger_context, rejected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill_id,
                    trigger_type,
                    proposed_type,
                    rejection_reason,
                    confidence,
                    trigger_context,
                    rejected_at_iso,
                ),
            )
            self._conn.commit()

    async def save_evolution_rejection(
        self,
        skill_id: str,
        trigger_type: str,
        proposed_type: str,
        rejection_reason: str,
        confidence: float = 0.5,
        trigger_context: str = "",
    ) -> None:
        """Record LLM rejection of an evolution candidate.

        Used for analyzing rule-based strategy effectiveness:
        - High rejection rate -> rule thresholds need tuning
        - Low confidence rejections -> unclear trigger context

        Args:
            skill_id: Skill identifier
            trigger_type: Which trigger produced the candidate, e.g. "tool_degradation"
            proposed_type: "FIX", "DERIVED", etc.
            rejection_reason: Why LLM rejected (from confirmation)
            confidence: LLM confidence in rejection decision (0.0-1.0)
            trigger_context: Context that triggered the evolution attempt
        """
        from datetime import datetime

        self._ensure_open()  # type: ignore[attr-defined]
        rejected_at_iso = datetime.now(UTC).isoformat()

        await asyncio.to_thread(
            self._save_rejection_sync,
            skill_id,
            trigger_type,
            proposed_type,
            rejection_reason,
            confidence,
            trigger_context,
            rejected_at_iso,
        )

    def load_rejections(self, skill_id: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        """Load evolution rejection records.

        Args:
            skill_id: Optional skill filter
            limit: Max records to return

        Returns:
            List of rejection dicts
        """
        self._ensure_open()  # type: ignore[attr-defined]
        with self._reader() as conn:  # type: ignore[attr-defined]
            if skill_id:
                rows = conn.execute(
                    """
                    SELECT skill_id, trigger_type, proposed_type, rejection_reason,
                           confidence, trigger_context, rejected_at
                    FROM evolution_rejections
                    WHERE skill_id = ?
                    ORDER BY rejected_at DESC
                    LIMIT ?
                    """,
                    (skill_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT skill_id, trigger_type, proposed_type, rejection_reason,
                           confidence, trigger_context, rejected_at
                    FROM evolution_rejections
                    ORDER BY rejected_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]

    # --- Evolution constraints ---

    def _add_evolution_constraint_sync(self, skill_id: str, constraint_text: str) -> None:
        """Synchronous constraint save."""
        from datetime import datetime

        with self._mu:
            self._conn.execute(
                """
                INSERT INTO evolution_constraints (skill_id, constraint_text, created_at)
                VALUES (?, ?, ?)
                """,
                (skill_id, constraint_text, datetime.now(UTC).isoformat()),
            )
            self._conn.commit()

    async def add_evolution_constraint(self, skill_id: str, constraint_text: str) -> None:
        """Add a constraint/lesson for a specific skill.

        Args:
            skill_id: Skill identifier
            constraint_text: The constraint or lesson to remember
        """
        if not constraint_text.strip():
            return

        self._ensure_open()  # type: ignore[attr-defined]
        await asyncio.to_thread(self._add_evolution_constraint_sync, skill_id, constraint_text.strip())

    def get_evolution_constraints(self, skill_id: str, limit: int = 5) -> list[str]:
        """Get recent constraints for a specific skill.

        Args:
            skill_id: Skill identifier
            limit: Max constraints to return

        Returns:
            List of constraint strings
        """
        self._ensure_open()  # type: ignore[attr-defined]
        with self._reader() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                """
                SELECT constraint_text
                FROM evolution_constraints
                WHERE skill_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (skill_id, limit),
            ).fetchall()
            return [row["constraint_text"] for row in rows]
