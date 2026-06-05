"""Complex query methods for SkillStore.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)

[OUTPUT]
- SkillStoreQueries: Mixin class for complex SkillStore queries, including Hybrid Retrieval.

[POS]
Complex query methods for SkillStore, including Hybrid Retrieval (Semantic Search).
"""

from __future__ import annotations

import logging
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EnvironmentFingerprint,
    SkillRecord,
)

logger = logging.getLogger(__name__)

__all__ = ["SkillStoreQueries"]


class SkillStoreQueries:
    """Mixin class for complex SkillStore queries."""

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
            params: list[Any] = []

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
            return [self._row_to_record(dict(row)) for row in rows]

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
            return [self._row_to_record(dict(row)) for row in rows]

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
                    (name),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM skills WHERE name = ? AND version = ?",
                    (name, version),
                ).fetchone()

            if not row:
                return None
            return self._row_to_record(dict(row))

    def get_skill_lineage(self, skill_id: str) -> list[SkillRecord]:
        """Get complete lineage (ancestors) of a skill.

        Args:
            skill_id: Skill identifier

        Returns:
            List of SkillRecords from root to current (oldest to newest)
        """
        self._ensure_open()
        lineage = []
        current_id = skill_id

        with self._reader() as conn:
            while current_id:
                row = conn.execute("SELECT * FROM skills WHERE skill_id = ?", (current_id,)).fetchone()
                if not row:
                    break
                record = self._row_to_record(dict(row))
                lineage.insert(0, record)  # Insert at front (oldest first)
                current_id = record.lineage.parent_id

        return lineage

    def _search_skills_sync(
        self,
        query: str,
        env_fingerprint: EnvironmentFingerprint | None = None,
        limit: int = 5,
        min_effective_rate: float = 0.7,
        agent_id: str | None = None,
        mounted_skill_ids: list[str] | None = None,
    ) -> list[SkillRecord]:
        """Synchronous fallback for SQLite LIKE search."""
        self._ensure_open()
        with self._reader() as conn:
            # Basic text search on name, description, and traps
            search_pattern = f"%{query}%"

            # Base query: active skills with acceptable success rate
            sql = """
                SELECT * FROM skills
                WHERE is_active = 1
                AND (name LIKE ? OR description LIKE ? OR traps LIKE ?)
                AND (CAST(success_count AS REAL) / NULLIF(applied_count, 0) >= ? OR applied_count < 3)
            """
            params: list[Any] = [
                search_pattern,
                search_pattern,
                search_pattern,
                min_effective_rate,
            ]

            if agent_id is not None:
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

            # If environment fingerprint is provided, we prefer strict matches on OS
            # Since environment is stored as JSON, we can use LIKE for a simple check,
            # or JSON functions if using SQLite 3.38+
            if env_fingerprint and env_fingerprint.os_platform:
                # We do a soft match: either environment is NULL, or it matches the OS
                sql += " AND (environment IS NULL OR environment LIKE ?)"
                params.append(f'%"{env_fingerprint.os_platform}"%')

            sql += " ORDER BY (CAST(success_count AS REAL) / NULLIF(applied_count, 0)) DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_record(dict(row)) for row in rows]

    async def search_skills(
        self,
        query: str,
        env_fingerprint: EnvironmentFingerprint | None = None,
        limit: int = 5,
        min_effective_rate: float = 0.7,
        agent_id: str | None = None,
        mounted_skill_ids: list[str] | None = None,
    ) -> list[SkillRecord]:
        """Search for skills matching a query and environment fingerprint.

        Uses Vector Semantic Memory layer (Hybrid Retrieval) if configured,
        falling back to SQLite LIKE search if unavailable or on error.
        """
        import asyncio

        vector_store = getattr(self, "_vector_store", None)
        embedding = getattr(self, "_embedding", None)
        collection_name = getattr(self, "VECTOR_COLLECTION_NAME", "skills_semantic")

        # Hybrid Search Path
        if vector_store and embedding:
            try:
                # 1. Embed query
                query_vector = await embedding.embed(query)

                # 2. Build Qdrant filters
                filters = {"is_active": 1}
                # We do NOT filter by os_platform in Qdrant because a skill might be cross-platform
                # (os_platform is None). Qdrant's simple filter builder doesn't support OR conditions easily.
                # We leave the precise environment filtering to the SQLite post-filtering step.

                # 3. Query Qdrant (fetch more to account for local filtering)
                fetch_limit = limit * 10
                results = await vector_store.search(
                    collection_name,
                    query_vector,
                    limit=fetch_limit,
                    filters=filters,
                )

                if results:
                    skill_ids = [r.document.id for r in results]

                    # 4. Fetch from SQLite and filter by metrics and environment
                    # We need to preserve the Qdrant order
                    placeholders = ",".join("?" * len(skill_ids))
                    sql = f"""
                        SELECT * FROM skills
                        WHERE skill_id IN ({placeholders})
                        AND (CAST(success_count AS REAL) / NULLIF(applied_count, 0) >= ? OR applied_count < 3)
                    """
                    params: list[Any] = [*skill_ids, min_effective_rate]

                    if agent_id is not None:
                        scope_clause = """
                            (
                                environment IS NULL
                                OR json_extract(environment, '$.custom_tags.scope_agent_id') IS NULL
                                OR json_extract(environment, '$.custom_tags.scope_agent_id') = ?
                            )
                        """
                        params.append(agent_id)

                        if mounted_skill_ids:
                            mounted_placeholders = ",".join("?" * len(mounted_skill_ids))
                            sql += f" AND ({scope_clause} OR skill_id IN ({mounted_placeholders}))"
                            params.extend(mounted_skill_ids)
                        else:
                            sql += f" AND {scope_clause}"

                    if env_fingerprint and env_fingerprint.os_platform:
                        sql += " AND (environment IS NULL OR environment LIKE ?)"
                        params.append(f'%"{env_fingerprint.os_platform}"%')

                    with self._reader() as conn:
                        rows = conn.execute(sql, tuple(params)).fetchall()

                    # Convert to records and sort by Qdrant order
                    records = {row["skill_id"]: self._row_to_record(dict(row)) for row in rows}
                    final_results = []
                    for sid in skill_ids:
                        if sid in records:
                            final_results.append(records[sid])
                            if len(final_results) >= limit:
                                break

                    return final_results
            except Exception as e:
                logger.warning(f"Vector search failed, falling back to SQLite LIKE: {e}")
                # Fallthrough to SQLite LIKE search

        # Fallback / Original SQLite LIKE search path
        return await asyncio.to_thread(
            self._search_skills_sync, query, env_fingerprint, limit, min_effective_rate, agent_id, mounted_skill_ids
        )

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

    async def get_agent_tool_health(self, agent_id: str, days: int = 7) -> list[dict[str, Any]]:
        """Get aggregated tool health metrics for a specific agent.

        Args:
            agent_id: The agent ID
            days: Lookback period in days

        Returns:
            List of dictionaries containing aggregated metrics per tool.
        """
        import asyncio
        from datetime import datetime, timedelta

        self._ensure_open()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        def _get_health() -> list[dict[str, Any]]:
            with self._reader() as conn:
                rows = conn.execute(
                    """
                    SELECT 
                        tool_name,
                        COUNT(*) as total_calls,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                        SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                        AVG(elapsed_time) as avg_duration,
                        MAX(elapsed_time) as max_duration
                    FROM tool_executions
                    WHERE agent_id = ? AND timestamp >= ?
                    GROUP BY tool_name
                    """,
                    (agent_id, cutoff),
                ).fetchall()

                return [dict(row) for row in rows]

        return await asyncio.to_thread(_get_health)
