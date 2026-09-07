"""Marathon task checkpoint manager with crash recovery.

Supports durable state checkpointing for multi-hour marathon tasks,
allowing seamless resume on transient crashes or interruptions.

[INPUT]
- typing: Any, Optional, Dict, List
- pathlib: Path

[OUTPUT]
- MarathonCheckpointer: Durable task checkpoint manager.

[POS]
Harness resilience checkpointer for long-running workflows.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


@dataclass(slots=True)
class MarathonCheckpointRecord:
    """A durable checkpoint snapshot of a marathon task."""

    checkpoint_id: str
    session_id: str
    step_index: int
    step_name: str
    timestamp: float
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    state_payload: dict[str, Any] = field(default_factory=dict)


class MarathonCheckpointer:
    """Manages durable state checkpoints for long-running agent tasks."""

    def __init__(self, storage_dir: Path | str | None = None) -> None:
        self.storage_dir = Path(storage_dir or "/tmp/myrm_marathon_checkpoints")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(
        self,
        *,
        session_id: str,
        step_index: int,
        step_name: str,
        completed_steps: list[str] | None = None,
        pending_steps: list[str] | None = None,
        state_payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MarathonCheckpointRecord:
        """Atomically persist a checkpoint snapshot to disk."""
        checkpoint_id = f"chk-{session_id}-{step_index:04d}-{uuid4().hex[:6]}"
        record = MarathonCheckpointRecord(
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            step_index=step_index,
            step_name=step_name,
            timestamp=time.time(),
            completed_steps=completed_steps or [],
            pending_steps=pending_steps or [],
            metadata=metadata or {},
            state_payload=state_payload or {},
        )

        session_dir = self.storage_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        file_path = session_dir / f"{step_index:04d}_{checkpoint_id}.json"

        temp_path = file_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(file_path)

        logger.info(
            "Saved marathon checkpoint: session=%s step=%d id=%s",
            session_id,
            step_index,
            checkpoint_id,
        )
        return record

    def load_latest_checkpoint(self, session_id: str) -> MarathonCheckpointRecord | None:
        """Load the most recent checkpoint for a session."""
        session_dir = self.storage_dir / session_id
        if not session_dir.exists():
            return None

        chk_files = sorted(session_dir.glob("*.json"))
        if not chk_files:
            return None

        latest_file = chk_files[-1]
        try:
            data = json.loads(latest_file.read_text(encoding="utf-8"))
            return MarathonCheckpointRecord(**data)
        except Exception:
            logger.warning("Failed loading checkpoint file: %s", latest_file, exc_info=True)
            return None

    def list_checkpoints(self, session_id: str) -> list[MarathonCheckpointRecord]:
        """List all available checkpoints for a session in chronological order."""
        session_dir = self.storage_dir / session_id
        if not session_dir.exists():
            return []

        records: list[MarathonCheckpointRecord] = []
        for file in sorted(session_dir.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                records.append(MarathonCheckpointRecord(**data))
            except Exception:
                continue
        return records

    def purge_session(self, session_id: str) -> None:
        """Remove all checkpoint files for a completed session."""
        session_dir = self.storage_dir / session_id
        if session_dir.exists():
            for file in session_dir.glob("*"):
                try:
                    file.unlink()
                except Exception:
                    pass
            try:
                session_dir.rmdir()
            except Exception:
                pass
