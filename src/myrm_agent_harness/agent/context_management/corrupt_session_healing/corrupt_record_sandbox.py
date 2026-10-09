"""Quarantine sandbox and archive manager for corrupted session records.

[INPUT]
- healing_types: CorruptRecordArchive, HealingSuiteConfig.

[OUTPUT]
- CorruptRecordSandbox: Safely writes corrupted snapshot payloads to an isolated
  quarantine vault and registers forensic diagnostics.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.corrupt_session_healing
- Module: corrupt_record_sandbox.py
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, Optional, Sequence
from myrm_agent_harness.agent.context_management.corrupt_session_healing.healing_types import (
    CorruptRecordArchive,
    HealingSuiteConfig,
)


class CorruptRecordSandbox:
    """Quarantines corrupted session data to prevent cascading failures."""

    def __init__(self, config: Optional[HealingSuiteConfig] = None) -> None:
        self._config = config or HealingSuiteConfig()
        self._archives: Dict[str, CorruptRecordArchive] = {}
        self._archive_dir = Path(self._config.archive_directory)

    def quarantine_payload(
        self,
        session_id: str,
        raw_payload: str,
        error_diagnostic: str,
        salvaged_count: int = 0,
    ) -> CorruptRecordArchive:
        """Quarantines a corrupt session payload by writing it to disk and tracking forensics.

        Args:
            session_id: Target session identifier.
            raw_payload: The raw corrupted payload string.
            error_diagnostic: Root cause error message or traceback summary.
            salvaged_count: Number of messages salvaged before failure.

        Returns:
            CorruptRecordArchive containing forensic metadata.
        """
        content_hash = hashlib.sha256(raw_payload.encode("utf-8", errors="replace")).hexdigest()
        epoch = time.time()

        # Ensure quarantine directory exists safely
        try:
            self._archive_dir.mkdir(parents=True, exist_ok=True)
            archive_filename = f"{session_id}_{content_hash[:12]}_{int(epoch)}.corrupt.json"
            target_path = self._archive_dir / archive_filename
            meta = {
                "session_id": session_id,
                "error": error_diagnostic,
                "archived_at_epoch": epoch,
                "content_hash": content_hash,
                "salvaged_count": salvaged_count,
                "raw_payload": raw_payload,
            }
            target_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            resolved_archive_path = str(target_path.resolve())
        except Exception as exc:
            resolved_archive_path = f"in-memory-fallback://{session_id}?err={exc}"

        archive = CorruptRecordArchive(
            corrupted_session_id=session_id,
            archive_path=resolved_archive_path,
            error_diagnostic=error_diagnostic,
            salvaged_message_count=salvaged_count,
            archived_at_epoch=epoch,
            content_hash=content_hash,
        )
        self._archives[session_id] = archive
        return archive

    def get_archive(self, session_id: str) -> Optional[CorruptRecordArchive]:
        """Retrieves quarantine record for a given session identifier."""
        return self._archives.get(session_id)

    def list_archives(self) -> Sequence[CorruptRecordArchive]:
        """Returns all registered corruption quarantine archives."""
        return tuple(self._archives.values())
