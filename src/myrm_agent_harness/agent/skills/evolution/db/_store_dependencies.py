"""Persistent skill dependency tracking for the skill evolution store.

Stores the resolved cross-skill dependency graph so impact analysis
(``get_dependents``) survives process restarts. Edges are maintained
incrementally whenever a skill record is saved or deleted.

[INPUT]
- agent.skills.evolution.execution.dependency::parse_skill_dependencies (POS: Skill dependency management for evolution safety.)

[OUTPUT]
- SkillDependencyMixin: Persistent skill dependency tracking for SkillStore.

[POS]
Persistent skill dependency tracking (graph edges, impact queries) for skill evolution system.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.skills.evolution.execution.dependency import parse_skill_dependencies

if TYPE_CHECKING:  # pragma: no cover
    from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord

logger = logging.getLogger(__name__)

__all__ = ["SkillDependencyMixin"]

_DEPENDENCY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS skill_dependencies (
    skill_id    TEXT NOT NULL,
    depends_on  TEXT NOT NULL,
    dep_type    TEXT NOT NULL DEFAULT 'skill',
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (skill_id, depends_on)
);
CREATE INDEX IF NOT EXISTS idx_skill_dependencies_depends_on
    ON skill_dependencies(depends_on);
CREATE INDEX IF NOT EXISTS idx_skill_dependencies_skill
    ON skill_dependencies(skill_id);
"""

_DEP_TYPE_SKILL = "skill"
_DEP_TYPE_TOOL = "tool"


class SkillDependencyMixin:
    """Persistent skill dependency tracking for SkillStore.

    Expects host class to have:
    - _mu: threading.Lock
    - _conn: sqlite3.Connection
    - _ensure_open(): None
    - _reader(): context manager yielding sqlite3.Connection

    Dependency edges are resolved at write time: the ``dependencies``
    frontmatter names are mapped to in-library skill IDs, and tool
    references are stored verbatim. Unresolved names are dropped so the
    graph only ever contains in-library edges.

    The ``*_locked`` methods assume the host's ``_mu`` lock is already
    held so they can be composed inside the host's write transactions.
    """

    _mu: threading.Lock
    _conn: sqlite3.Connection

    def _build_dependency_rows(self, record: SkillRecord, now: str) -> list[tuple[str, str, str, str]]:
        """Resolve and build dependency rows for a skill record (lock not required).

        Args:
            record: SkillRecord to resolve dependencies for.
            now: ISO-8601 timestamp shared across the batch.

        Returns:
            Rows of ``(skill_id, depends_on, dep_type, updated_at)``.
        """
        parsed = parse_skill_dependencies(record.content or "")
        rows: list[tuple[str, str, str, str]] = []
        if parsed.skill_deps:
            # Map declared skill names to in-library skill IDs so the graph
            # only contains edges we can actually resolve. The edge key is the
            # depended-on skill's ID, matching the impact queries' key space.
            placeholders = ",".join("?" for _ in parsed.skill_deps)
            found = {
                row[0]
                for row in self._conn.execute(
                    f"SELECT skill_id FROM skills WHERE name IN ({placeholders})",
                    parsed.skill_deps,
                ).fetchall()
            }
            rows.extend((record.skill_id, skill_id, _DEP_TYPE_SKILL, now) for skill_id in found)
        rows.extend((record.skill_id, tool, _DEP_TYPE_TOOL, now) for tool in parsed.tool_deps)
        return rows

    def _sync_skill_dependencies_locked(self, record: SkillRecord) -> None:
        """Replace a skill's dependency edges (host lock already held).

        Args:
            record: SkillRecord whose dependencies should be persisted.
        """
        rows = self._build_dependency_rows(record, datetime.now(UTC).isoformat())
        self._conn.execute("DELETE FROM skill_dependencies WHERE skill_id = ?", (record.skill_id,))
        if rows:
            self._conn.executemany(
                "INSERT OR IGNORE INTO skill_dependencies "
                "(skill_id, depends_on, dep_type, updated_at) VALUES (?, ?, ?, ?)",
                rows,
            )

    def _sync_skills_dependencies_locked(self, records: list[SkillRecord]) -> None:
        """Replace dependency edges for a batch of records (host lock held).

        Args:
            records: SkillRecords whose dependencies should be persisted.
        """
        now = datetime.now(UTC).isoformat()
        for record in records:
            rows = self._build_dependency_rows(record, now)
            self._conn.execute("DELETE FROM skill_dependencies WHERE skill_id = ?", (record.skill_id,))
            if rows:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO skill_dependencies "
                    "(skill_id, depends_on, dep_type, updated_at) VALUES (?, ?, ?, ?)",
                    rows,
                )

    def _delete_skill_dependencies_locked(self, skill_id: str) -> None:
        """Remove every edge touching a skill (host lock held).

        Args:
            skill_id: Skill identifier that no longer exists.
        """
        self._conn.execute(
            "DELETE FROM skill_dependencies WHERE skill_id = ? OR depends_on = ?",
            (skill_id, skill_id),
        )

    async def sync_skill_dependencies(self, record: object) -> None:
        """Persist dependency edges for a skill record (idempotent).

        Use this only for out-of-band content updates; regular saves go
        through :meth:`SkillStore.save_skill`, which already maintains edges.

        Args:
            record: SkillRecord to persist dependencies for.
        """
        self._ensure_open()  # type: ignore[attr-defined]
        await asyncio.to_thread(self._sync_skill_dependencies_locked, record)

    async def delete_skill_dependencies(self, skill_id: str) -> None:
        """Remove dependency edges for a deleted skill.

        Args:
            skill_id: Skill identifier that no longer exists.
        """
        self._ensure_open()  # type: ignore[attr-defined]
        await asyncio.to_thread(self._delete_skill_dependencies_locked, skill_id)

    def get_dependents(self, skill_id: str) -> list[str]:
        """List skill IDs that declare a dependency on the given skill.

        Args:
            skill_id: Skill identifier to inspect.

        Returns:
            In-library skill IDs that depend on ``skill_id``.
        """
        self._ensure_open()  # type: ignore[attr-defined]
        with self._reader() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                """
                SELECT skill_id FROM skill_dependencies
                WHERE depends_on = ? AND dep_type = ?
                ORDER BY skill_id
                """,
                (skill_id, _DEP_TYPE_SKILL),
            ).fetchall()
            return [row["skill_id"] for row in rows]

    def get_dependents_map(self, skill_ids: list[str]) -> dict[str, list[str]]:
        """Batch variant of :meth:`get_dependents` for list endpoints.

        Args:
            skill_ids: Skill identifiers to inspect.

        Returns:
            Mapping of skill ID to in-library dependent skill IDs.
        """
        if not skill_ids:
            return {}
        self._ensure_open()  # type: ignore[attr-defined]
        with self._reader() as conn:  # type: ignore[attr-defined]
            placeholders = ",".join("?" for _ in skill_ids)
            rows = conn.execute(
                f"""
                SELECT skill_id, depends_on FROM skill_dependencies
                WHERE depends_on IN ({placeholders}) AND dep_type = ?
                ORDER BY skill_id
                """,
                (*skill_ids, _DEP_TYPE_SKILL),
            ).fetchall()
        result: dict[str, list[str]] = {sid: [] for sid in skill_ids}
        for row in rows:
            result.setdefault(row["depends_on"], []).append(row["skill_id"])
        return result

    def get_skill_dependencies(self, skill_id: str) -> list[str]:
        """List in-library skills the given skill depends on.

        Args:
            skill_id: Skill identifier to inspect.

        Returns:
            In-library skill IDs declared in ``dependencies``.
        """
        self._ensure_open()  # type: ignore[attr-defined]
        with self._reader() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                """
                SELECT depends_on FROM skill_dependencies
                WHERE skill_id = ? AND dep_type = ?
                ORDER BY depends_on
                """,
                (skill_id, _DEP_TYPE_SKILL),
            ).fetchall()
            return [row["depends_on"] for row in rows]
