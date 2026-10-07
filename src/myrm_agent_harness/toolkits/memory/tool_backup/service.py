"""[POS]: src/myrm_agent_harness/toolkits/memory/tool_backup/service.py
[INPUT]: ToolUseDatabase, ToolUseBackupRecorder, and DurableToolUseStore dependencies.
[OUTPUT]: ToolUseBackupService unified facade managing durable tool use backup index.
"""

from pathlib import Path

from .db import ToolUseDatabase
from .models import ToolUseQueryFilter, ToolUseRecord, ToolUseStats, ToolUseStatus
from .recorder import ToolUseBackupRecorder
from .store import DurableToolUseStore


class ToolUseBackupService:
    """Unified facade service orchestrating durable tool use logging and audit lookups."""

    def __init__(
        self,
        db_path: Path | str = ":memory:",
        max_output_bytes: int = 256 * 1024,
    ) -> None:
        self._db = ToolUseDatabase(db_path=db_path)
        conn = self._db.get_connection()
        self._recorder = ToolUseBackupRecorder(conn=conn, max_output_bytes=max_output_bytes)
        self._store = DurableToolUseStore(conn=conn)

    @property
    def recorder(self) -> ToolUseBackupRecorder:
        """Access the low-level fail-safe recorder."""
        return self._recorder

    @property
    def store(self) -> DurableToolUseStore:
        """Access the durable query store."""
        return self._store

    def record_tool_use(
        self,
        session_id: str,
        tool_name: str,
        raw_input: str,
        raw_output: str,
        tool_call_id: str = "",
        status: ToolUseStatus = ToolUseStatus.SUCCESS,
        duration_ms: float = 0.0,
        metadata: dict[str, str] | None = None,
        created_at_epoch: float | None = None,
    ) -> ToolUseRecord | None:
        """Persist a tool invocation execution record."""
        return self._recorder.record_tool_use(
            session_id=session_id,
            tool_name=tool_name,
            raw_input=raw_input,
            raw_output=raw_output,
            tool_call_id=tool_call_id,
            status=status,
            duration_ms=duration_ms,
            metadata=metadata,
            created_at_epoch=created_at_epoch,
        )

    def get_tool_use(self, tool_use_id: str) -> ToolUseRecord | None:
        """Retrieve an exact tool use record by ID."""
        return self._store.get(tool_use_id)

    def query_tool_uses(self, filter_spec: ToolUseQueryFilter) -> list[ToolUseRecord]:
        """Query tool use records matching filter criteria."""
        return self._store.query(filter_spec)

    def get_stats(self, session_id: str | None = None) -> ToolUseStats:
        """Compute tool invocation metrics globally or for a specific session."""
        return self._store.get_stats(session_id=session_id)

    def purge_session(self, session_id: str) -> int:
        """Remove all tool uses associated with a pruned session."""
        return self._store.delete_session_tool_uses(session_id=session_id)

    def close(self) -> None:
        """Close underlying database connection."""
        self._db.close()
