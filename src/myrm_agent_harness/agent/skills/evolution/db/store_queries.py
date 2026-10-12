"""Complex query methods for SkillStore.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)

[OUTPUT]
- SkillStoreQueries: Mixin class for complex SkillStore queries.

[POS]
Complex query methods for SkillStore.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord

logger = logging.getLogger(__name__)

__all__ = ["SkillStoreQueries"]

SqlParam = str | float


class SkillStoreQueries:
    """Mixin class for complex SkillStore queries."""

    if TYPE_CHECKING:
        # Provided by SkillStore, the host class of this mixin.
        def _ensure_open(self) -> None: ...
        def _reader(self) -> AbstractContextManager[sqlite3.Connection]: ...
        def _row_to_record(self, sqlite_row: sqlite3.Row) -> SkillRecord: ...

    def get_active_skills(
        self,
        agent_id: str | None = None,
        mounted_skill_ids: list[str] | None = None,
    ) -> list[SkillRecord]:
        """Load all active skills, filtered by agent scope.

        Args:
            agent_id: If provided, filters to skills owned by this agent,
                      or global skills (no owner).
            mounted_skill_ids: Optional list of specific skill IDs to include
                               (e.g. skills mounted from other agents).

        Returns:
            List of active SkillRecords
        """
        self._ensure_open()
        with self._reader() as conn:
            sql = "SELECT * FROM skills WHERE is_active = 1"
            params: list[SqlParam] = []

            if agent_id is not None:
                # Build scope isolation logic
                # A skill is included if it's global (no scope) or owned by this agent
                scope_clause = """
                    (
                        environment IS NULL
                        OR json_extract(environment, '$.custom_tags.scope_agent_id') IS NULL
                        OR json_extract(environment, '$.custom_tags.scope_agent_id') = ?
                    )
                """
                params.append(agent_id)

                if mounted_skill_ids:
                    placeholders = ",".join("?" * len(mounted_skill_ids))
                    sql += f" AND ({scope_clause} OR skill_id IN ({placeholders}))"
                    params.extend(mounted_skill_ids)
                else:
                    sql += f" AND {scope_clause}"

            sql += " ORDER BY updated_at DESC"

            rows = conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_record(row) for row in rows]

    def get_skills_needing_fix(self, threshold: float = 0.5) -> list[SkillRecord]:
        """Find skills with low success rate or consecutive failures.

        Args:
            threshold: Success rate threshold (default 0.5)

        Returns:
            List of skills needing FIX evolution
        """
        self._ensure_open()
        with self._reader() as conn:
            # Debug: check all skills first
            all_skills = conn.execute(
                "SELECT skill_id, consecutive_failures, applied_count, success_count, is_active FROM skills"
            ).fetchall()
            logger.debug(f"All skills in DB: {[dict(row) for row in all_skills]}")

            rows = conn.execute(
                """
                SELECT * FROM skills
                WHERE is_active = 1
                AND (
                    (CAST(success_count AS REAL) / NULLIF(applied_count, 0) < ? AND applied_count >= 3)
                    OR consecutive_failures >= 3
                )
                ORDER BY consecutive_failures DESC, CAST(success_count AS REAL) / NULLIF(applied_count, 0) ASC
                """,
                (threshold,),
            ).fetchall()

            logger.debug(f"Skills needing fix (threshold={threshold}): {len(rows)} found")
            return [self._row_to_record(row) for row in rows]

    def get_skill_by_name_version(self, name: str, version: int | None = None) -> SkillRecord | None:
        """Load skill by name and optional version.

        Args:
            name: Skill name
            version: Specific version (if None, returns latest active version)

        Returns:
            SkillRecord or None if not found
        """
        self._ensure_open()
        with self._reader() as conn:
            if version is None:
                row = conn.execute(
                    """
                    SELECT * FROM skills
                    WHERE name = ? AND is_active = 1
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (name,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM skills WHERE name = ? AND version = ?",
                    (name, version),
                ).fetchone()

            if not row:
                return None
            return self._row_to_record(row)

    def get_skill_lineage(self, skill_id: str) -> list[SkillRecord]:
        """Get complete lineage (ancestors) of a skill.

        Args:
            skill_id: Skill identifier

        Returns:
            List of SkillRecords from root to current (oldest to newest).
            Malformed parent chains (self-reference or cycles) are terminated
            defensively instead of looping forever.
        """
        self._ensure_open()
        lineage: list[SkillRecord] = []
        current_id: str | None = skill_id
        seen: set[str] = set()

        with self._reader() as conn:
            while current_id and current_id not in seen:
                seen.add(current_id)
                row = conn.execute("SELECT * FROM skills WHERE skill_id = ?", (current_id,)).fetchone()
                if not row:
                    break
                record = self._row_to_record(row)
                lineage.insert(0, record)  # Insert at front (oldest first)
                current_id = record.lineage.parent_id

        return lineage

    def get_recent_analyses_grouped(self, days: int = 7) -> dict[str, list[dict[str, str | bool]]]:
        """Group recent execution analyses by skill_id.

        Returns a dict mapping skill_id to a list of analysis row dicts
        (including both success and failure records).

        Args:
            days: Number of days to look back (default 7)

        Returns:
            Dict mapping skill_id -> list of analysis row dicts
        """
        from collections import defaultdict
        from datetime import datetime, timedelta

        self._ensure_open()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._reader() as conn:
            rows = conn.execute(
                """
                SELECT skill_id, task_id, success, error_message,
                       root_cause, suggested_fix, task_context, analyzed_at
                FROM execution_analyses
                WHERE analyzed_at >= ?
                ORDER BY skill_id, analyzed_at DESC
                """,
                (cutoff,),
            ).fetchall()

        groups: dict[str, list[dict[str, str | bool]]] = defaultdict(list)
        for row in rows:
            groups[row["skill_id"]].append(dict(row))

        return dict(groups)

    def get_trend_failure_counts(self, days: int = 30) -> dict[str, int]:
        """Get failure counts per skill over a longer trend window.

        Used for slow-degradation detection: catches skills that fail
        infrequently (e.g., 1/week) but consistently over a longer period.

        Args:
            days: Trend lookback window (default 30)

        Returns:
            Dict mapping skill_id -> failure count in the trend window
        """
        from datetime import datetime, timedelta

        self._ensure_open()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._reader() as conn:
            rows = conn.execute(
                """
                SELECT skill_id, COUNT(*) as fail_count
                FROM execution_analyses
                WHERE analyzed_at >= ? AND success = 0
                GROUP BY skill_id
                """,
                (cutoff,),
            ).fetchall()

        return {row["skill_id"]: row["fail_count"] for row in rows}
