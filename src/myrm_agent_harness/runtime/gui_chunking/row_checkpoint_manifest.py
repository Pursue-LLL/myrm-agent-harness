"""Row-level progress checkpoint manifest with crash-safe atomic filesystem persistence.

Benchmarked against OpenAI Codex Computer Use Principle 2 (Atomic Checkpoint Files):
- Tracks granular progress for every row item in batch automation tasks (e.g. 5000 rows).
- Saves intermediate state after every single row to prevent discarding completed work on crash.
- Enforces atomic write protocol (temp file + os.replace) to avoid partial-write corruptions.
- Immediately surfaces pending / failed rows for seamless skip-ahead resumption.

[OUTPUT]
- RowCheckpointManifest: Crash-resilient row-level state ledger backed by atomic JSON persistence.

[INPUT]
- __future__
- json
- os
- time
- pathlib

[OUTPUT]
- RowCheckpointManifest

[POS]
Row-level progress checkpoint manifest with crash-safe atomic filesystem persistence.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from myrm_agent_harness.runtime.gui_chunking.chunking_types import (
    BatchPipelineProgress,
    PipelineStageKind,
    RowCheckpointItem,
    RowProcessingStatus,
)


class RowCheckpointManifest:
    """Manages transactional row-level progress records stored on local disk."""

    def __init__(self, manifest_path: Path | str) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.pipeline_id: str = "pipeline_default"
        self.stage: PipelineStageKind = PipelineStageKind.BATCH_EXECUTION
        # Ordered row records: row_id -> RowCheckpointItem
        self._rows: dict[str, RowCheckpointItem] = {}

        if self.manifest_path.exists():
            self._load()

    def _persist_atomic(self) -> None:
        """Write manifest contents to a temporary file, then atomically replace target."""
        temp_file = self.manifest_path.with_suffix(f".tmp.{os.getpid()}.{time.time()}")
        payload = {
            "pipeline_id": self.pipeline_id,
            "stage": self.stage.value,
            "updated_at": time.time(),
            "rows": [
                {
                    "row_id": r.row_id,
                    "payload": r.payload,
                    "status": r.status.value,
                    "proof_artifact_path": r.proof_artifact_path,
                    "error_message": r.error_message,
                    "updated_at": r.updated_at,
                }
                for r in self._rows.values()
            ],
        }

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_file, self.manifest_path)

    def _load(self) -> None:
        """Load manifest state from disk into memory."""
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                data = json.load(f)
            self.pipeline_id = str(data.get("pipeline_id", "pipeline_default"))
            self.stage = PipelineStageKind(data.get("stage", PipelineStageKind.BATCH_EXECUTION.value))
            self._rows.clear()
            for item in data.get("rows", []):
                r_item = RowCheckpointItem(
                    row_id=str(item["row_id"]),
                    payload=dict(item.get("payload", {})),
                    status=RowProcessingStatus(item["status"]),
                    proof_artifact_path=str(item.get("proof_artifact_path", "")),
                    error_message=str(item.get("error_message", "")),
                    updated_at=float(item.get("updated_at", time.time())),
                )
                self._rows[r_item.row_id] = r_item
        except (json.JSONDecodeError, KeyError, OSError):
            # If load fails due to unexpected corruption, keep current in-memory state
            pass

    def init_manifest(
        self,
        pipeline_id: str,
        rows: list[tuple[str, dict[str, str]]] | tuple[tuple[str, dict[str, str]], ...],
        stage: PipelineStageKind = PipelineStageKind.BATCH_EXECUTION,
    ) -> None:
        """Initialize or reset manifest with input items awaiting processing."""
        self.pipeline_id = pipeline_id
        self.stage = stage
        self._rows.clear()
        now = time.time()

        for r_id, payload in rows:
            self._rows[r_id] = RowCheckpointItem(
                row_id=r_id,
                payload=dict(payload),
                status=RowProcessingStatus.PENDING,
                updated_at=now,
            )

        self._persist_atomic()

    def mark_success(self, row_id: str, proof_path: str = "") -> None:
        """Mark an individual row as successfully executed with optional screenshot/receipt proof."""
        item = self._rows.get(row_id)
        if item is None:
            return

        self._rows[row_id] = RowCheckpointItem(
            row_id=row_id,
            payload=item.payload,
            status=RowProcessingStatus.SUCCESS,
            proof_artifact_path=proof_path,
            error_message="",
            updated_at=time.time(),
        )
        self._persist_atomic()

    def mark_failed(self, row_id: str, error_msg: str) -> None:
        """Mark an individual row as failed with captured error diagnostic."""
        item = self._rows.get(row_id)
        if item is None:
            return

        self._rows[row_id] = RowCheckpointItem(
            row_id=row_id,
            payload=item.payload,
            status=RowProcessingStatus.FAILED,
            proof_artifact_path="",
            error_message=error_msg,
            updated_at=time.time(),
        )
        self._persist_atomic()

    def get_pending_rows(self) -> list[RowCheckpointItem]:
        """Fetch all rows that are either PENDING or FAILED, skipping completed ones."""
        return [
            r for r in self._rows.values()
            if r.status in (RowProcessingStatus.PENDING, RowProcessingStatus.FAILED)
        ]

    def get_row(self, row_id: str) -> RowCheckpointItem | None:
        """Retrieve the checkpoint record for a specific row ID."""
        return self._rows.get(row_id)

    def get_progress(self) -> BatchPipelineProgress:
        """Compute execution metrics across all rows."""
        total = len(self._rows)
        completed = sum(1 for r in self._rows.values() if r.status == RowProcessingStatus.SUCCESS)
        failed = sum(1 for r in self._rows.values() if r.status == RowProcessingStatus.FAILED)
        skipped = sum(1 for r in self._rows.values() if r.status == RowProcessingStatus.SKIPPED)
        is_done = total > 0 and (completed + skipped) == total

        return BatchPipelineProgress(
            pipeline_id=self.pipeline_id,
            stage=self.stage,
            total_rows=total,
            completed_rows=completed,
            failed_rows=failed,
            skipped_rows=skipped,
            is_finished=is_done,
            manifest_path=str(self.manifest_path),
        )
