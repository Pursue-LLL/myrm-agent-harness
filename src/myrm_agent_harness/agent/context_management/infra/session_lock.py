"""Session-level context lock manager.

1. This file's INPUT/OUTPUT/POS comments.

[INPUT]
- asyncio::Lock (POS: Python async lock)
- contextvars::contextvars (POS: Python context variables)
- contextlib::asynccontextmanager (POS: async context manager decorator)

[OUTPUT]
- get_session_lock: returns a session lock.
- acquire_context_lock: async context manager for context mutation locks.
- is_context_lock_held: returns whether the current task holds a session lock.
- cleanup_unused_locks: clears unused locks.

[POS]
Session-level lock manager. Provides per-session async locks ensuring serialized context mutations within a session while allowing cross-session parallelism. Includes automatic cleanup.

"""

import asyncio
import contextvars
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

# Session lock storage.
_session_locks: dict[str, asyncio.Lock] = {}
_lock_last_used: dict[str, float] = {}

# Lock configuration.
_LOCK_CLEANUP_THRESHOLD_SECONDS = 3600
_locks_mutex = asyncio.Lock()

# Current session ID propagated through contextvars.
_current_chat_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_chat_id", default=None)
_held_chat_ids: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar(
    "held_context_chat_ids",
    default=frozenset(),
)


def set_current_chat_id(chat_id: str) -> contextvars.Token[str | None]:
    """Set the current chat ID.

    Args:
        chat_id: Chat ID.

    Returns:
        Token for restoring the previous value.
    """
    return _current_chat_id.set(chat_id)


def get_current_chat_id() -> str | None:
    """Return the current chat ID.

    Returns:
        Current chat ID, or None when unset.
    """
    return _current_chat_id.get()


def reset_current_chat_id(token: contextvars.Token[str | None]) -> None:
    """Reset the current chat ID.

    Args:
        token: Token returned by set_current_chat_id.
    """
    _current_chat_id.reset(token)


def is_context_lock_held(chat_id: str | None = None) -> bool:
    """Return whether the current task already owns the context lock."""
    effective_chat_id = chat_id or get_current_chat_id()
    return bool(effective_chat_id and effective_chat_id in _held_chat_ids.get())


async def get_session_lock(chat_id: str) -> asyncio.Lock:
    """Return the lock for a chat session.

    Creates a new lock when the session has no existing lock and cleans up
    expired idle locks.

    Args:
        chat_id: Chat ID.

    Returns:
        The asyncio.Lock for this chat.
    """
    async with _locks_mutex:
        current_time = time.time()
        _lock_last_used[chat_id] = current_time

        if chat_id in _session_locks:
            return _session_locks[chat_id]

        lock = asyncio.Lock()
        _session_locks[chat_id] = lock

        await _cleanup_expired_locks(current_time)

        return lock


async def _cleanup_expired_locks(current_time: float) -> None:
    """Clean up expired session locks.

    Args:
        current_time: Current timestamp.
    """
    expired_sessions = [
        chat_id
        for chat_id, last_used in _lock_last_used.items()
        if current_time - last_used > _LOCK_CLEANUP_THRESHOLD_SECONDS
    ]

    for chat_id in expired_sessions:
        lock = _session_locks.get(chat_id)
        if lock and not lock.locked():
            del _session_locks[chat_id]
            del _lock_last_used[chat_id]


@asynccontextmanager
async def acquire_context_lock(chat_id: str | None = None) -> AsyncGenerator[None]:
    """Acquire the context mutation lock.

    Serializes context mutation operations such as compression and summarization.

    Args:
        chat_id: Chat ID. When None, resolves it from contextvars.

    Yields:
        None. The lock is released when the context exits.

    Example:
        async with acquire_context_lock(chat_id):
            # Run compression or summarization.
            new_messages = await compress_messages(messages)
    """
    effective_chat_id = chat_id or get_current_chat_id() or "default"
    held_chat_ids = _held_chat_ids.get()
    if effective_chat_id in held_chat_ids:
        yield
        return

    lock = await get_session_lock(effective_chat_id)

    async with lock:
        token = _held_chat_ids.set(held_chat_ids | {effective_chat_id})
        try:
            yield
        finally:
            _held_chat_ids.reset(token)


def get_active_session_count() -> int:
    """Return active session lock count for monitoring.

    Returns:
        Active session lock count.
    """
    return len(_session_locks)


def get_locked_session_count() -> int:
    """Return held session lock count for monitoring.

    Returns:
        Held session lock count.
    """
    return sum(1 for lock in _session_locks.values() if lock.locked())


async def clear_all_locks() -> None:
    """Clear all session locks. Intended for tests."""
    async with _locks_mutex:
        _session_locks.clear()
        _lock_last_used.clear()
