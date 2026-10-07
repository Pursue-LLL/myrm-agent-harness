"""[POS]: src/myrm_agent_harness/toolkits/memory/tool_backup/store.py
[INPUT]: SQLite connection and ToolUseQueryFilter search constraints.
[OUTPUT]: DurableToolUseStore engine providing precise lookups, queries, and audit statistics.
"""

import json
import sqlite3

from .models import ToolUseQueryFilter, ToolUseRecord, ToolUseStats, ToolUseStatus


class DurableToolUseStore:
    """Query and management store for durable side-indexed tool executions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, tool_use_id: str) -> ToolUseRecord | None:
        """Retrieve a specific tool use record by unique identifier."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT
                id, session_id, tool_name, tool_call_id,
                raw_input, raw_output, status, duration_ms,
                created_at_epoch, is_truncated, original_output_bytes,
                metadata_json
            FROM myrm_tool_uses
            WHERE id = ?
            """,
            (tool_use_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def query(self, filter_spec: ToolUseQueryFilter) -> list[ToolUseRecord]:
        """Query tool use records matching filter criteria with pagination."""
        conditions: list[str] = []
        params: list[str | int] = []

        if filter_spec.session_id:
            conditions.append("session_id = ?")
            params.append(filter_spec.session_id)

        if filter_spec.tool_name:
            conditions.append("tool_name = ?")
            params.append(filter_spec.tool_name)

        if filter_spec.status:
            conditions.append("status = ?")
            params.append(str(filter_spec.status))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query_sql = f"""
            SELECT
                id, session_id, tool_name, tool_call_id,
                raw_input, raw_output, status, duration_ms,
                created_at_epoch, is_truncated, original_output_bytes,
                metadata_json
            FROM myrm_tool_uses
            {where_clause}
            ORDER BY created_at_epoch DESC
            LIMIT ? OFFSET ?
        """
        params.extend([filter_spec.limit, filter_spec.offset])

        cursor = self._conn.cursor()
        cursor.execute(query_sql, params)
        rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_stats(self, session_id: str | None = None) -> ToolUseStats:
        """Compute aggregate invocation metrics globally or for a specific session."""
        cursor = self._conn.cursor()
        where_clause = "WHERE session_id = ?" if session_id else ""
        params = (session_id,) if session_id else ()

        sql = f"""
            SELECT
                COUNT(*),
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END),
                AVG(duration_ms)
            FROM myrm_tool_uses
            {where_clause}
        """
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if not row or row[0] == 0:
            return ToolUseStats(
                total_tool_uses=0,
                success_count=0,
                error_count=0,
                avg_duration_ms=0.0,
            )

        total_count = int(row[0]) if row[0] is not None else 0
        success_count = int(row[1]) if row[1] is not None else 0
        error_count = int(row[2]) if row[2] is not None else 0
        avg_duration = float(row[3]) if row[3] is not None else 0.0

        return ToolUseStats(
            total_tool_uses=total_count,
            success_count=success_count,
            error_count=error_count,
            avg_duration_ms=round(avg_duration, 2),
        )

    def delete_session_tool_uses(self, session_id: str) -> int:
        """Purge tool use records associated with a deleted session."""
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM myrm_tool_uses WHERE session_id = ?", (session_id,))
        deleted_count = cursor.rowcount
        self._conn.commit()
        return deleted_count

    @staticmethod
    def _row_to_record(row: tuple[object, ...]) -> ToolUseRecord:
        meta_dict: dict[str, str] = {}
        if row[11]:
            try:
                meta_dict = json.loads(str(row[11]))
            except json.JSONDecodeError:
                meta_dict = {}

        return ToolUseRecord(
            id=str(row[0]),
            session_id=str(row[1]),
            tool_name=str(row[2]),
            tool_call_id=str(row[3]),
            raw_input=str(row[4]),
            raw_output=str(row[5]),
            status=ToolUseStatus(str(row[6])),
            duration_ms=float(row[7]) if row[7] is not None else 0.0,
            created_at_epoch=float(row[8]),
            is_truncated=bool(row[9]),
            original_output_bytes=int(row[10]) if row[10] is not None else 0,
            metadata=meta_dict,
        )
