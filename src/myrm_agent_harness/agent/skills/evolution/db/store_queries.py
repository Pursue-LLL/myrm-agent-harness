"""Complex query methods for SkillStore.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)

[OUTPUT]
- SkillStoreQueries: Mixin class for complex SkillStore queries.

[POS]
Complex query methods for SkillStore.
"""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord

__all__ = ["SkillStoreQueries"]

SqlParam = str | float

# A skill is in an agent's scope when it is global (no owner) or owned by that agent.
_AGENT_SCOPE_CLAUSE = """
    (
        environment IS NULL
        OR json_extract(environment, '$.custom_tags.scope_agent_id') IS NULL
        OR json_extract(environment, '$.custom_tags.scope_agent_id') = ?
    )
"""


def _active_skills_filter(
    agent_id: str | None,
    mounted_skill_ids: list[str] | None = None,
) -> tuple[str, list[SqlParam]]:
    """Build the WHERE condition and bound params selecting active skills visible to ``agent_id``."""
    condition = "is_active = 1"
    params: list[SqlParam] = []
    if agent_id is None:
        return condition, params

    params.append(agent_id)
    if mounted_skill_ids:
        placeholders = ",".join("?" * len(mounted_skill_ids))
        condition += f" AND ({_AGENT_SCOPE_CLAUSE} OR skill_id IN ({placeholders}))"
        params.extend(mounted_skill_ids)
    else:
        condition += f" AND {_AGENT_SCOPE_CLAUSE}"
    return condition, params


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
        condition, params = _active_skills_filter(agent_id, mounted_skill_ids)
        with self._reader() as conn:
            rows = conn.execute(
                f"SELECT * FROM skills WHERE {condition} ORDER BY updated_at DESC",
                tuple(params),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def count_active_skills(self, agent_id: str | None = None) -> int:
        """Count active skills visible to ``agent_id`` without loading skill bodies.

        Uses the same scope rule as :meth:`get_active_skills`.
        """
        self._ensure_open()
        condition, params = _active_skills_filter(agent_id)
        with self._reader() as conn:
            row = conn.execute(f"SELECT COUNT(*) FROM skills WHERE {condition}", tuple(params)).fetchone()
            return int(row[0])

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
