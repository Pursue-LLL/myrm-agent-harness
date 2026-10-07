"""Storage layer for Session Step Checkpoints supporting atomic persistence.

Persists step snapshots with atomic write-and-rename guarantees on disk,
while providing memory-fallback when no physical storage path is configured.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from myrm_agent_harness.runtime.context.session_checkpoint_types import (
    CheckpointStepStatus,
    SessionCheckpointConfig,
    SessionStepCheckpoint,
    ToolExecutionSnapshot,
)


class SessionCheckpointStorage:
    """Atomic storage provider for step-level execution checkpoints."""

    def __init__(self, config: SessionCheckpointConfig | None = None) -> None:
        self._config = config or SessionCheckpointConfig()
        self._memory_store: dict[str, list[SessionStepCheckpoint]] = {}
        if self._config.storage_dir:
            Path(self._config.storage_dir).mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, checkpoint: SessionStepCheckpoint) -> None:
        """Persist a checkpoint atomically, respecting max retention limits."""
        sess_id = checkpoint.session_id
        session_list = self._memory_store.setdefault(sess_id, [])
        session_list.append(checkpoint)

        # Enforce in-memory retention ceiling
        if len(session_list) > self._config.max_checkpoints_per_session:
            session_list.pop(0)

        # On-disk atomic write if directory configured
        if self._config.storage_dir:
            self._write_to_disk_atomic(checkpoint)

    def get_latest_checkpoint(
        self, session_id: str
    ) -> SessionStepCheckpoint | None:
        """Retrieve the latest step checkpoint recorded for the given session."""
        items = self.list_checkpoints(session_id)
        return items[-1] if items else None

    def get_checkpoint(
        self, session_id: str, checkpoint_id: str
    ) -> SessionStepCheckpoint | None:
        """Find a specific checkpoint by session and checkpoint ID."""
        for ckpt in self.list_checkpoints(session_id):
            if ckpt.checkpoint_id == checkpoint_id:
                return ckpt
        return None

    def list_checkpoints(self, session_id: str) -> list[SessionStepCheckpoint]:
        """List all preserved checkpoints for a session ordered chronologically."""
        if self._config.storage_dir:
            disk_items = self._load_from_disk(session_id)
            if disk_items:
                return disk_items
        return list(self._memory_store.get(session_id, []))

    def clear_session(self, session_id: str) -> None:
        """Purge in-memory and on-disk checkpoints for the specified session."""
        self._memory_store.pop(session_id, None)
        if self._config.storage_dir:
            sess_dir = Path(self._config.storage_dir) / session_id
            if sess_dir.exists() and sess_dir.is_dir():
                for p in sess_dir.glob("*.json"):
                    p.unlink(missing_ok=True)
                sess_dir.rmdir()

    def _write_to_disk_atomic(self, checkpoint: SessionStepCheckpoint) -> None:
        """Write checkpoint JSON using write-to-tmp then atomic replace."""
        if not self._config.storage_dir:
            return
        sess_dir = Path(self._config.storage_dir) / checkpoint.session_id
        sess_dir.mkdir(parents=True, exist_ok=True)

        target_file = sess_dir / f"{checkpoint.step_index:06d}_{int(checkpoint.timestamp * 1000):013d}_{checkpoint.checkpoint_id}.json"
        temp_file = sess_dir / f"{target_file.name}.tmp"

        payload = self._serialize_checkpoint(checkpoint)
        temp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_file, target_file)

    def _load_from_disk(self, session_id: str) -> list[SessionStepCheckpoint]:
        """Load and deserialize all checkpoint files from the session directory."""
        if not self._config.storage_dir:
            return []
        sess_dir = Path(self._config.storage_dir) / session_id
        if not sess_dir.exists() or not sess_dir.is_dir():
            return []

        checkpoints: list[SessionStepCheckpoint] = []
        for file_path in sess_dir.glob("*.json"):
            try:
                raw_json = file_path.read_text(encoding="utf-8")
                data = json.loads(raw_json)
                checkpoints.append(self._deserialize_checkpoint(data))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        checkpoints.sort(key=lambda cp: (cp.step_index, cp.timestamp))
        return checkpoints

    @staticmethod
    def _serialize_checkpoint(
        cp: SessionStepCheckpoint,
    ) -> dict[str, str | int | float | dict[str, str] | dict[str, str | float | bool | dict[str, str]] | None]:
        """Convert checkpoint to a JSON-serializable dictionary."""
        pending_data: dict[str, str | float | bool | dict[str, str]] | None = None
        if cp.pending_tool_call is not None:
            pending_data = {
                "tool_name": cp.pending_tool_call.tool_name,
                "call_id": cp.pending_tool_call.call_id,
                "input_args": dict(cp.pending_tool_call.input_args),
                "is_idempotent": cp.pending_tool_call.is_idempotent,
                "output_preview": cp.pending_tool_call.output_preview or "",
                "executed_at": cp.pending_tool_call.executed_at,
            }

        return {
            "checkpoint_id": cp.checkpoint_id,
            "session_id": cp.session_id,
            "step_index": cp.step_index,
            "status": cp.status.value,
            "workspace_fingerprint": cp.workspace_fingerprint,
            "messages_count": cp.messages_count,
            "pending_tool_call": pending_data,
            "timestamp": cp.timestamp,
            "metadata": dict(cp.metadata),
        }

    @staticmethod
    def _deserialize_checkpoint(
        data: dict[str, str | int | float | dict[str, str] | dict[str, str | float | bool | dict[str, str]] | None],
    ) -> SessionStepCheckpoint:
        """Reconstruct SessionStepCheckpoint from serialized dictionary."""
        pending: ToolExecutionSnapshot | None = None
        raw_pending = data.get("pending_tool_call")
        if isinstance(raw_pending, dict):
            raw_args = raw_pending.get("input_args", {})
            safe_args: dict[str, str] = {
                str(k): str(v) for k, v in raw_args.items()
            } if isinstance(raw_args, dict) else {}
            pending = ToolExecutionSnapshot(
                tool_name=str(raw_pending.get("tool_name", "")),
                call_id=str(raw_pending.get("call_id", "")),
                input_args=safe_args,
                is_idempotent=bool(raw_pending.get("is_idempotent", False)),
                output_preview=str(raw_pending.get("output_preview", "")) or None,
                executed_at=float(raw_pending.get("executed_at", 0.0)),
            )

        raw_meta = data.get("metadata", {})
        meta: dict[str, str] = {
            str(k): str(v) for k, v in raw_meta.items()
        } if isinstance(raw_meta, dict) else {}

        return SessionStepCheckpoint(
            checkpoint_id=str(data.get("checkpoint_id", "")),
            session_id=str(data.get("session_id", "")),
            step_index=int(data.get("step_index", 0)),
            status=CheckpointStepStatus(str(data.get("status", CheckpointStepStatus.INITIALIZED.value))),
            workspace_fingerprint=str(data.get("workspace_fingerprint", "")),
            messages_count=int(data.get("messages_count", 0)),
            pending_tool_call=pending,
            timestamp=float(data.get("timestamp", 0.0)),
            metadata=meta,
        )
