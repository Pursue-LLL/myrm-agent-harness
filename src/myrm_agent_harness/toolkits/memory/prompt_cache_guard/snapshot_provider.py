"""Snapshot provider for immutable in-context resident memory with prompt cache stability.

[INPUT]
myrm_agent_harness.toolkits.memory.prompt_cache_guard.models::FrozenMemorySnapshot (POS: 不可变常驻记忆快照模型)

[OUTPUT]
FrozenMemorySnapshotProvider: Lifecycle manager binding immutable memory snapshots to active sessions, ensuring 100% prefix cache hits.

[POS]
前缀缓存稳定守卫之不可变快照提供者。会话启动时生成确定性不可变快照并在整个会话生命周期内绝对锁定，
会话内发生的所有写入操作均标记为 pending_next_session 并在底层落盘，活跃快照字节级不变，
彻底根治会话中途修改记忆导致 LLM 前缀缓存击穿与首字延迟暴增。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from threading import Lock

from myrm_agent_harness.toolkits.memory.prompt_cache_guard.models import (
    FrozenMemorySnapshot,
)

logger = logging.getLogger(__name__)


def _format_markdown_list(items: list[str]) -> str:
    """Format list of string rules/memories into clean bulleted markdown."""
    clean_items = [item.strip() for item in items if item.strip()]
    if not clean_items:
        return ""
    return "\n".join(f"- {item}" for item in clean_items)


def _compute_snapshot_hash(memory_text: str, user_text: str) -> str:
    """Compute deterministic SHA-256 fingerprint for snapshot versioning."""
    digest = hashlib.sha256()
    digest.update(memory_text.encode("utf-8"))
    digest.update(b":::")
    digest.update(user_text.encode("utf-8"))
    return digest.hexdigest()[:16]


class FrozenMemorySnapshotProvider:
    """Session-scoped manager providing immutable resident memory snapshots."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active_snapshots: dict[str, FrozenMemorySnapshot] = {}
        self._pending_mutations: dict[str, list[tuple[str, str]]] = {}

    def get_or_create_snapshot(
        self,
        session_id: str,
        memory_items: list[str],
        user_items: list[str],
    ) -> FrozenMemorySnapshot:
        """Get existing immutable snapshot or create and lock a new one for this session."""
        with self._lock:
            existing = self._active_snapshots.get(session_id)
            if existing is not None:
                return existing

            memory_md = _format_markdown_list(memory_items)
            user_md = _format_markdown_list(user_items)
            version = _compute_snapshot_hash(memory_md, user_md)

            snapshot = FrozenMemorySnapshot(
                session_id=session_id,
                memory_content=memory_md,
                user_profile_content=user_md,
                snapshot_version=version,
                created_at=datetime.now(UTC),
                pending_updates_count=0,
            )
            self._active_snapshots[session_id] = snapshot
            self._pending_mutations[session_id] = []
            logger.info(
                f"Frozen memory snapshot initialized for session {session_id} (version={version}, "
                f"memory_chars={len(memory_md)}, user_chars={len(user_md)})"
            )
            return snapshot

    def get_active_snapshot(self, session_id: str) -> FrozenMemorySnapshot | None:
        """Retrieve currently locked snapshot for the given session without mutation."""
        with self._lock:
            return self._active_snapshots.get(session_id)

    def record_in_session_mutation(
        self,
        session_id: str,
        category: str,
        content: str,
    ) -> None:
        """Record in-session mutation. Increments pending count without mutating active prompt text."""
        with self._lock:
            current = self._active_snapshots.get(session_id)
            if current is None:
                logger.warning(f"Recording mutation for untracked session {session_id}")
                return

            mutations = self._pending_mutations.setdefault(session_id, [])
            mutations.append((category, content))

            # Replace snapshot object with incremented pending_updates_count,
            # keeping memory_content and user_profile_content 100% BYTE-FOR-BYTE IDENTICAL.
            updated = FrozenMemorySnapshot(
                session_id=current.session_id,
                memory_content=current.memory_content,
                user_profile_content=current.user_profile_content,
                snapshot_version=current.snapshot_version,
                created_at=current.created_at,
                pending_updates_count=current.pending_updates_count + 1,
            )
            self._active_snapshots[session_id] = updated
            logger.debug(
                f"In-session memory mutation recorded for {session_id} (pending_count={updated.pending_updates_count}). "
                f"Active prefix text remains 100% frozen."
            )

    def get_pending_mutations(self, session_id: str) -> list[tuple[str, str]]:
        """Return all staged in-session mutations awaiting next-session compile."""
        with self._lock:
            return list(self._pending_mutations.get(session_id, []))

    def compile_next_session_snapshot(
        self,
        session_id: str,
        new_memory_items: list[str],
        new_user_items: list[str],
    ) -> FrozenMemorySnapshot:
        """Compile a refreshed snapshot for a new session or explicit reset."""
        with self._lock:
            memory_md = _format_markdown_list(new_memory_items)
            user_md = _format_markdown_list(new_user_items)
            version = _compute_snapshot_hash(memory_md, user_md)

            new_snapshot = FrozenMemorySnapshot(
                session_id=session_id,
                memory_content=memory_md,
                user_profile_content=user_md,
                snapshot_version=version,
                created_at=datetime.now(UTC),
                pending_updates_count=0,
            )
            self._active_snapshots[session_id] = new_snapshot
            self._pending_mutations[session_id] = []
            return new_snapshot

    def clear_session(self, session_id: str) -> None:
        """Evict session snapshot from active registry upon session termination."""
        with self._lock:
            self._active_snapshots.pop(session_id, None)
            self._pending_mutations.pop(session_id, None)
