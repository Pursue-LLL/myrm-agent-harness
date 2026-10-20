"""JSONL-based skill history backend implementation.

[INPUT]
- .protocols::SkillHistoryBackend (POS: Protocol interface)
- .types::SkillHistoryRecord (POS: History record data class)
- json, pathlib (POS: Standard library)

[OUTPUT]
- JsonlHistoryBackend: JSONL file history backend

[POS]
Implements SkillHistoryBackend using JSONL files for history storage.
Each skill's history stored in: {history_root}/{user_id}/{skill_name}.jsonl
Format: one JSON record per line, with automatic timestamp and serialization.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .protocols import SkillHistoryBackend
from .types import SkillHistoryRecord

logger = logging.getLogger(__name__)


class JsonlHistoryBackend(SkillHistoryBackend):
    """JSONL file-based history backend.

    Storage structure:
        {history_root}/
        ├── my-skill.jsonl
        └── another-skill.jsonl
    """

    def __init__(self, history_root: Path | str):
        """Initialize backend.

        Args:
            history_root: Root directory for history files
        """
        self.history_root = Path(history_root).expanduser()
        self.history_root.mkdir(parents=True, exist_ok=True)

    def _get_history_file(self, skill_name: str) -> Path:
        """Get history file path for a skill."""
        return self.history_root / f"{skill_name}.jsonl"

    async def append_history(
        self,
        skill_name: str,
        record: SkillHistoryRecord,
    ) -> None:
        """Append history record to JSONL file."""
        history_file = self._get_history_file(skill_name)

        payload = {
            "action": record.action,
            "author": record.author,
            "timestamp": record.timestamp.isoformat(),
            "file_path": record.file_path,
            "prev_content": record.prev_content,
            "new_content": record.new_content,
            "thread_id": record.thread_id,
            "session_id": record.session_id,
            "request_id": record.request_id,
            "user_agent": record.user_agent,
            "scanner": record.scanner,
            "metadata": record.metadata,
        }

        try:
            with history_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False))
                f.write("\n")
        except Exception as e:
            logger.error(f"Failed to append history for skill {skill_name}: {e}")
            raise

    async def list_history(
        self,
        skill_name: str,
        limit: int = 100,
    ) -> list[SkillHistoryRecord]:
        """List history records (newest first)."""
        history_file = self._get_history_file(skill_name)

        if not history_file.exists():
            return []

        try:
            records: list[SkillHistoryRecord] = []
            for line in history_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue

                data = json.loads(line)
                record = SkillHistoryRecord(
                    action=data["action"],
                    author=data["author"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    file_path=data["file_path"],
                    prev_content=data.get("prev_content"),
                    new_content=data.get("new_content"),
                    thread_id=data.get("thread_id"),
                    session_id=data.get("session_id"),
                    request_id=data.get("request_id"),
                    user_agent=data.get("user_agent"),
                    scanner=data.get("scanner"),
                    metadata=data.get("metadata"),
                )
                records.append(record)

            records.reverse()
            return records[:limit]

        except Exception as e:
            logger.error(f"Failed to read history for skill {skill_name}: {e}")
            return []

    async def get_history_count(
        self,
        skill_name: str,
    ) -> int:
        """Get total history count."""
        history_file = self._get_history_file(skill_name)

        if not history_file.exists():
            return 0

        try:
            count = 0
            for line in history_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    count += 1
            return count
        except Exception as e:
            logger.error(f"Failed to count history for skill {skill_name}: {e}")
            return 0
