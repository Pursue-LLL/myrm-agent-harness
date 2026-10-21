"""Idle session freezer and memory offloader.

Evicts dormant sessions from resident heap memory to volume storage,
allowing a single agent worker to host 10x more nominal concurrent sessions.

[INPUT]
- __future__
- json
- tempfile
- time
- pathlib
- memory_sentinel_types

[OUTPUT]
- IdleSessionFreezer

[POS]
Idle session freezer and memory offloader.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from .memory_sentinel_types import (
    BoundedCacheStats,
    SessionSnapshotRecord,
)


class IdleSessionFreezer:
    """Manages active session residency in memory and serializes idle sessions to disk."""

    def __init__(self, storage_dir: Path | str) -> None:
        self.storage_dir = Path(storage_dir) / "frozen_sessions"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._active_sessions: dict[str, list[dict[str, str]]] = {}
        self._last_access: dict[str, float] = {}

    def set_session(self, session_id: str, messages: list[dict[str, str]]) -> None:
        """Store or update session messages in active memory, recording access timestamp."""
        self._active_sessions[session_id] = list(messages)
        self._last_access[session_id] = time.time()

    def get_or_wake_session(self, session_id: str) -> list[dict[str, str]] | None:
        """Retrieve session messages from memory, or transparently rehydrate from disk if frozen."""
        now = time.time()
        if session_id in self._active_sessions:
            self._last_access[session_id] = now
            return self._active_sessions[session_id]

        # Check if session is frozen on disk
        freeze_file = self.storage_dir / f"{session_id}.json"
        if freeze_file.exists():
            try:
                with freeze_file.open("r", encoding="utf-8") as f:
                    raw_msgs = json.load(f)

                messages: list[dict[str, str]] = [
                    {str(k): str(v) for k, v in item.items()}
                    for item in raw_msgs
                    if isinstance(item, dict)
                ]
                self._active_sessions[session_id] = messages
                self._last_access[session_id] = now
                return messages
            except (json.JSONDecodeError, OSError):
                return None

        return None

    def sweep_and_freeze_idle_sessions(
        self,
        idle_timeout_s: float = 1800.0,  # 30 minutes default
    ) -> list[SessionSnapshotRecord]:
        """Scan active sessions and unload those exceeding idle_timeout_s to disk."""
        now = time.time()
        frozen_records: list[SessionSnapshotRecord] = []
        sessions_to_freeze: list[str] = []

        for sid, last_t in self._last_access.items():
            if now - last_t >= idle_timeout_s:
                sessions_to_freeze.append(sid)

        for sid in sessions_to_freeze:
            messages = self._active_sessions.pop(sid, [])
            self._last_access.pop(sid, None)

            freeze_file = self.storage_dir / f"{sid}.json"
            with tempfile.NamedTemporaryFile("w", dir=self.storage_dir, delete=False, encoding="utf-8") as tmp:
                json.dump(messages, tmp, indent=2, ensure_ascii=False)
                tmp_path = Path(tmp.name)

            tmp_path.replace(freeze_file)

            record = SessionSnapshotRecord(
                session_id=sid,
                message_count=len(messages),
                storage_file=freeze_file,
                frozen_at=time.time(),
            )
            frozen_records.append(record)

        return frozen_records

    def get_resident_count(self) -> int:
        """Return the count of sessions currently resident in heap memory."""
        return len(self._active_sessions)

    def render_memory_governance_markdown(
        self,
        cache_stats: BoundedCacheStats,
    ) -> str:
        """Render a GitHub Flavored Markdown card showing memory telemetry and eviction health."""
        resident_sessions = self.get_resident_count()
        frozen_files = list(self.storage_dir.glob("*.json"))
        cache_mb = round(cache_stats.current_bytes / (1024 * 1024), 2)
        max_mb = round(cache_stats.max_bytes / (1024 * 1024), 2)

        lines: list[str] = [
            "### 🧠 确定性内存生命周期与有界缓存防爆看板",
            f"- **活跃驻留内存会话**: `{resident_sessions}` 个",
            f"- **已冻结休眠会话**: `{len(frozen_files)}` 个",
            f"- **有界缓存当前字节**: `{cache_mb}MB` / 上限 `{max_mb}MB`",
            f"- **缓存条目数**: `{cache_stats.item_count}` / `{cache_stats.max_items}`",
            f"- **累计淘汰逐出条目**: `{cache_stats.eviction_count}`",
            "",
        ]

        if cache_stats.eviction_count > 0:
            lines.extend(
                [
                    "> [!NOTE]",
                    f"> **[防爆机制生效中]** 已成功触发 {cache_stats.eviction_count} 次三维淘汰（TTL/LRU/字节上限），常驻内存被锁定在安全区间内。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!TIP]",
                    "> 当前堆内存占用健康，闲置会话与超大工具输出均受脱水管道与冻结机制严格保护。",
                ]
            )

        return "\n".join(lines)
