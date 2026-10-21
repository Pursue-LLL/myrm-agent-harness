"""Filesystem-level in-flight conflict resolution & lock engine (Item 59).

[INPUT]
- File lock acquisition requests, release directives, and renewal heartbeats from
  collaborating humans and subagents.

[OUTPUT]
- Lease-based file and line-range locks preventing overlapping concurrent writes
  without requiring asynchronous Git branching.

[POS]
- Core concurrency coordination component for multi-human multi-agent co-dev.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

from myrm_agent_harness.agent.sub_agents.virtual_room.types import (
    FileBlockLeaseLock,
    LockScopeEnum,
    ParticipantRoleEnum,
)


class VirtualFilesystemLockEngine:
    """Manages ephemeral in-flight block lease locks over shared project files."""

    def __init__(self, default_ttl_seconds: float = 15.0) -> None:
        self._default_ttl_seconds = max(1.0, min(120.0, default_ttl_seconds))
        self._locks: dict[str, FileBlockLeaseLock] = {}

    def _purge_expired_locks(self, now: float) -> None:
        """Removes all leases that have surpassed their validity expiration timestamp."""
        expired_ids = [
            lock_id
            for lock_id, lock in self._locks.items()
            if lock.expires_at <= now
        ]
        for lock_id in expired_ids:
            del self._locks[lock_id]

    def acquire_lock(
        self,
        file_path: str,
        holder_id: str,
        holder_role: ParticipantRoleEnum,
        start_line: int | None = None,
        end_line: int | None = None,
        scope: LockScopeEnum = LockScopeEnum.FILE_FULL,
        ttl_seconds: float | None = None,
    ) -> FileBlockLeaseLock:
        """Acquires a collaborative write lease on a whole file or specific line range."""
        now = time.time()
        self._purge_expired_locks(now)

        normalized_path = file_path.strip().replace("\\", "/")
        if not normalized_path:
            raise ValueError("Target file path cannot be empty.")

        if scope == LockScopeEnum.LINE_RANGE and (
            start_line is None or end_line is None or start_line <= 0 or end_line < start_line
        ):
            raise ValueError(
                f"Invalid line range [{start_line}, {end_line}] for file '{normalized_path}'."
            )

        # Evaluate potential overlap conflicts with active locks held by other participants
        for active in self._locks.values():
            if active.file_path != normalized_path or active.holder_id == holder_id:
                continue

            # Conflict case 1: Existing lock is full file
            if active.scope == LockScopeEnum.FILE_FULL:
                raise ValueError(
                    f"File '{normalized_path}' is fully locked by {active.holder_role.value} "
                    f"'{active.holder_id}' until {active.expires_at:.1f}."
                )

            # Conflict case 2: Incoming request is full file while a line range is locked
            if scope == LockScopeEnum.FILE_FULL:
                raise ValueError(
                    f"Cannot acquire full lock on '{normalized_path}': line range "
                    f"[{active.start_line}, {active.end_line}] is currently held by '{active.holder_id}'."
                )

            # Conflict case 3: Line ranges overlap
            if (
                active.scope == LockScopeEnum.LINE_RANGE
                and start_line is not None
                and end_line is not None
                and active.start_line is not None
                and active.end_line is not None
            ):
                has_overlap = not (end_line < active.start_line or start_line > active.end_line)
                if has_overlap:
                    raise ValueError(
                        f"Line range [{start_line}, {end_line}] overlaps with existing lock "
                        f"[{active.start_line}, {active.end_line}] held by '{active.holder_id}'."
                    )

        duration = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        clamped_ttl = max(1.0, min(120.0, duration))
        lock_id = f"lock-{uuid.uuid4().hex[:8]}"

        new_lock = FileBlockLeaseLock(
            lock_id=lock_id,
            file_path=normalized_path,
            holder_id=holder_id,
            holder_role=holder_role,
            scope=scope,
            start_line=start_line if scope == LockScopeEnum.LINE_RANGE else None,
            end_line=end_line if scope == LockScopeEnum.LINE_RANGE else None,
            acquired_at=now,
            expires_at=now + clamped_ttl,
            ttl_seconds=clamped_ttl,
        )
        self._locks[lock_id] = new_lock
        return new_lock

    def release_lock(self, lock_id: str, holder_id: str) -> bool:
        """Explicitly releases an active write lease."""
        if lock_id not in self._locks:
            return False
        lock = self._locks[lock_id]
        if lock.holder_id != holder_id:
            raise PermissionError(
                f"Holder '{holder_id}' is not authorized to release lock '{lock_id}' "
                f"held by '{lock.holder_id}'."
            )
        del self._locks[lock_id]
        return True

    def renew_lock(
        self,
        lock_id: str,
        holder_id: str,
        extension_seconds: float = 15.0,
    ) -> FileBlockLeaseLock:
        """Extends the lease validity of an active lock."""
        now = time.time()
        self._purge_expired_locks(now)

        if lock_id not in self._locks:
            raise KeyError(f"Lock '{lock_id}' does not exist or has already expired.")

        current = self._locks[lock_id]
        if current.holder_id != holder_id:
            raise PermissionError(
                f"Holder '{holder_id}' cannot renew lock held by '{current.holder_id}'."
            )

        clamped_extension = max(1.0, min(120.0, extension_seconds))
        updated_lock = FileBlockLeaseLock(
            lock_id=current.lock_id,
            file_path=current.file_path,
            holder_id=current.holder_id,
            holder_role=current.holder_role,
            scope=current.scope,
            start_line=current.start_line,
            end_line=current.end_line,
            acquired_at=current.acquired_at,
            expires_at=now + clamped_extension,
            ttl_seconds=clamped_extension,
        )
        self._locks[lock_id] = updated_lock
        return updated_lock

    def is_write_allowed(
        self,
        file_path: str,
        holder_id: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> bool:
        """Checks if a participant can safely write to a target file region."""
        now = time.time()
        self._purge_expired_locks(now)
        normalized_path = file_path.strip().replace("\\", "/")

        for active in self._locks.values():
            if active.file_path != normalized_path or active.holder_id == holder_id:
                continue

            # Another actor holds full file lock
            if active.scope == LockScopeEnum.FILE_FULL:
                return False

            # Incoming is full file while someone holds partial lock
            if start_line is None or end_line is None:
                return False

            # Checking line overlap
            if (
                active.start_line is not None
                and active.end_line is not None
                and not (end_line < active.start_line or start_line > active.end_line)
            ):
                return False

        return True

    def list_active_locks(self, file_path: str | None = None) -> Sequence[FileBlockLeaseLock]:
        """Returns all currently valid active locks, optionally filtered by file."""
        now = time.time()
        self._purge_expired_locks(now)
        if file_path is None:
            return tuple(self._locks.values())
        normalized_path = file_path.strip().replace("\\", "/")
        return tuple(
            lock_item
            for lock_item in self._locks.values()
            if lock_item.file_path == normalized_path
        )

    def clear(self) -> None:
        """Resets all tracked locks."""
        self._locks.clear()
