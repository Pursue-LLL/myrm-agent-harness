"""[POS]: src/myrm_agent_harness/toolkits/memory/tool_backup/recorder.py
[INPUT]: Raw tool input/output observations, execution timings, and metadata parameters.
[OUTPUT]: Fail-safe ToolUseBackupRecorder writing durable tool use snapshots.
"""

import json
import logging
import sqlite3
import time
import uuid

from .models import ToolUseRecord, ToolUseStatus

logger = logging.getLogger(__name__)


class ToolUseBackupRecorder:
    """Fail-safe side-index recorder capturing exact tool inputs and outputs."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        max_output_bytes: int = 256 * 1024,
    ) -> None:
        self._conn = conn
        self.max_output_bytes = max_output_bytes

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
        """Atomically persist a tool use execution record with fail-safe isolation."""
        try:
            record_id = f"tu_{uuid.uuid4().hex[:12]}"
            now_epoch = created_at_epoch if created_at_epoch is not None else time.time()
            meta_dict = metadata or {}

            # Handle output truncation safely
            output_bytes = len(raw_output.encode("utf-8"))
            is_truncated = False
            stored_output = raw_output

            if output_bytes > self.max_output_bytes:
                is_truncated = True
                half_limit = self.max_output_bytes // 2
                raw_bytes = raw_output.encode("utf-8")
                head_part = raw_bytes[:half_limit].decode("utf-8", errors="ignore")
                tail_part = raw_bytes[-half_limit:].decode("utf-8", errors="ignore")
                stored_output = (
                    f"{head_part}\n\n... [TRUNCATED {output_bytes - self.max_output_bytes} BYTES] ...\n\n{tail_part}"
                )

            record = ToolUseRecord(
                id=record_id,
                session_id=session_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                raw_input=raw_input,
                raw_output=stored_output,
                status=status,
                duration_ms=round(duration_ms, 2),
                created_at_epoch=now_epoch,
                is_truncated=is_truncated,
                original_output_bytes=output_bytes,
                metadata=meta_dict,
            )

            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO myrm_tool_uses (
                    id, session_id, tool_name, tool_call_id,
                    raw_input, raw_output, status, duration_ms,
                    created_at_epoch, is_truncated, original_output_bytes,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.session_id,
                    record.tool_name,
                    record.tool_call_id,
                    record.raw_input,
                    record.raw_output,
                    str(record.status),
                    record.duration_ms,
                    record.created_at_epoch,
                    1 if record.is_truncated else 0,
                    record.original_output_bytes,
                    json.dumps(record.metadata),
                ),
            )
            self._conn.commit()
            return record

        except Exception as exc:
            # Strict fail-safe guarantee: Never fail tool execution due to backup persistence error
            logger.error(
                "Failed to persist tool use backup for tool '%s' in session '%s': %s",
                tool_name,
                session_id,
                exc,
                exc_info=True,
            )
            return None
