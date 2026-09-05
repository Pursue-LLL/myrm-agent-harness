"""Persistent allowlist for allow-always tool approval decisions.

[INPUT]
- agent.security.command_allowlist_pattern::matches_command_pattern (POS: command allowlist wildcard/exact matcher)

[OUTPUT]
- DEFAULT_USER_ID: Framework-level sentinel user ID for single-user environments
- AllowlistEntry: persistent allow-always record
- Allowlist: in-memory allowlist with DB persistence
- AllowlistStore: persistence protocol

[POS]
Core component for "Always Allow" feature in Human-in-the-Loop approval system.
Works with middlewares/approval/ subsystem which uses LangGraph interrupt() for approval flow.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from myrm_agent_harness.agent.security.command_allowlist_pattern import matches_command_pattern

logger = logging.getLogger(__name__)

# Framework-level sentinel user ID for single-user (sandbox) environments.
# Aligns with the business layer convention (LOCAL_USER_ID = "sandbox").
DEFAULT_USER_ID: str = "sandbox"

# Opportunistic eviction: remove users whose cache timestamp is older than ttl * this factor (only when ttl > 0).
ALLOWLIST_STALE_CACHE_FACTOR: float = 2.0


@dataclass(frozen=True, slots=True)
class AllowlistEntry:
    """A persistent allow-always record with four matching granularities.

    Matching levels:
    1. Exact match: matches tool + arguments (tool_args_hash set)
    2. Pattern match: matches tool + command glob (command_pattern set)
    3. Tool-level: matches specific tool (tool_name set, no hash/pattern)
    4. Permission-level: matches all tools of permission type (tool_name=None)

    Identity Scope:
    - agent_id: Optional agent identity scope. For hosted MCP tools (mcp_invoke / mcp__*),
      binding agent_id guarantees that another agent cannot unintentionally inherit or hijack
      this permission (Confused Deputy Protection).

    Session Lifetime Scope:
    - session_id: Optional session identifier. When set, this entry is scoped strictly
      to the current conversation session (e.g. session-only duration) and MUST NEVER
      be persisted to long-term storage or leak across sessions.
    """

    permission: str
    tool_name: str | None = None
    tool_args_hash: str | None = None
    command_pattern: str | None = None
    agent_id: str | None = None
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    session_id: str | None = None


class AllowlistStore(Protocol):
    """Persistent backend for allow-always entries (DB, JSON file, etc.).

    All methods receive ``user_id`` as first parameter. In single-user
    (sandbox) environments this is typically ``DEFAULT_USER_ID`` ("sandbox").
    """

    async def load(self, user_id: str) -> Sequence[AllowlistEntry]: ...
    async def save(self, user_id: str, entry: AllowlistEntry) -> None: ...
    async def remove(
        self,
        user_id: str,
        permission: str,
        tool_name: str | None = None,
        tool_args_hash: str | None = None,
        command_pattern: str | None = None,
        agent_id: str | None = None,
    ) -> None: ...


class Allowlist:
    """In-memory allowlist with optional persistent backend.

    Features:
    - Concurrency-safe: per-user lock with double-checked locking
    - TTL refresh: when ttl_seconds > 0, cache expires after that many seconds
    - ttl_seconds <= 0: time-based expiry disabled (reload only when not yet loaded)
    - Automatic cleanup: when TTL enabled, expired locks removed opportunistically

    Performance:
    - Hot path (load_user cache hit): O(1) dict lookup plus freshness check
    - Hot path (check): O(n) linear scan where n = user's allowlist size, typically <10 entries
    - Measured: 0.0002ms (1 entry) to 0.0012ms (50 entries), negligible overhead
    - Memory: when ttl_seconds > 0, opportunistic cleanup drops inactive users after
      ttl_seconds * ALLOWLIST_STALE_CACHE_FACTOR (default 2.0); when ttl_seconds <= 0,
      entries persist for the process lifetime (bounded by distinct user_ids)
    """

    def __init__(self, store: AllowlistStore | None = None, ttl_seconds: float = 300.0) -> None:
        self._entries: dict[str, dict[tuple[str, str | None, str | None, str | None, str | None], AllowlistEntry]] = {}
        self._store = store
        self._cache_meta: dict[str, tuple[float | None, asyncio.Lock]] = {}
        self._meta_lock = asyncio.Lock()
        self._ttl = float(ttl_seconds)

    def _get_or_create_lock(self, user_id: str) -> tuple[float | None, asyncio.Lock, bool]:
        """Get cache metadata for user, create if needed (must hold _meta_lock).

        Returns:
            (timestamp, lock, is_new): timestamp is None for newly created locks
        """
        if user_id in self._cache_meta:
            ts, lock = self._cache_meta[user_id]
            return ts, lock, False
        return None, asyncio.Lock(), True

    def _is_cache_fresh(self, loaded_at: float | None) -> bool:
        """True if in-memory data for the user should be used without reloading from store."""
        if loaded_at is None:
            return False
        if self._ttl <= 0:
            return True
        return time.time() - loaded_at < self._ttl

    def _cleanup_expired_locks(self) -> None:
        """Remove locks for users with expired cache (opportunistic cleanup)."""
        if self._ttl <= 0:
            return
        now = time.time()
        expired = [
            uid
            for uid, (ts, _) in self._cache_meta.items()
            if ts is not None and now - ts > self._ttl * ALLOWLIST_STALE_CACHE_FACTOR
        ]
        for uid in expired:
            self._cache_meta.pop(uid, None)
            self._entries.pop(uid, None)

        if expired:
            logger.debug("[ALLOWLIST] Cleaned up %d expired locks (active: %d)", len(expired), len(self._cache_meta))

    async def load_user(self, user_id: str) -> None:
        """Load entries from persistent store into memory (concurrency-safe, with TTL).

        TTL mechanism when ttl_seconds > 0 ensures multi-instance cache consistency:
        - Cache expires after ttl_seconds (default 5min)
        - Expired entries are reloaded from DB
        - Expired locks are cleaned up opportunistically
        When ttl_seconds <= 0, time-based expiry and TTL cleanup are disabled.
        """
        # Fast path: check cache without lock
        if user_id in self._cache_meta:
            ts, _ = self._cache_meta[user_id]
            if self._is_cache_fresh(ts):
                return

        if not self._store:
            return

        # Acquire per-user lock
        async with self._meta_lock:
            ts, lock, is_new = self._get_or_create_lock(user_id)
            if is_new:
                self._cleanup_expired_locks()
                self._cache_meta[user_id] = (None, lock)

        async with lock:
            # Double-check TTL inside lock
            if user_id in self._cache_meta:
                ts, _ = self._cache_meta[user_id]
                if self._is_cache_fresh(ts):
                    return

            entries = await self._store.load(user_id)
            # Preserve existing session-scoped entries in memory when reloading DB entries
            current_session_entries = {
                k: v for k, v in self._entries.get(user_id, {}).items() if v.session_id is not None
            }
            loaded_entries = {
                (e.permission, e.tool_name, e.tool_args_hash, e.command_pattern, e.agent_id, e.session_id): e
                for e in entries
            }
            loaded_entries.update(current_session_entries)
            self._entries[user_id] = loaded_entries
            self._cache_meta[user_id] = (time.time(), lock)

    def check(
        self,
        user_id: str,
        permission_type: str,
        tool_name: str | None = None,
        tool_args_hash: str | None = None,
        *,
        command: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Check if the tool is in the user's allowlist with identity scope validation.

        Matching priority:
        1. Exact match: (permission, tool_name, tool_args_hash) all match + agent/session scope matches
        2. Pattern match: (permission, tool_name, command_pattern) glob match + agent/session scope matches
        3. Tool-level: (permission, tool_name) match, no args_hash/pattern constraint + agent/session scope matches
        4. Permission-level: permission match, no tool constraints + agent/session scope matches

        Args:
            user_id: User identifier
            permission_type: Permission type (e.g., 'code_interpreter', 'shell_exec', 'mcp_invoke')
            tool_name: Optional specific tool name for fine-grained matching
            tool_args_hash: Optional pre-computed hash for exact match (SHA256[:16])
            command: Optional shell command for pattern matching
            agent_id: Optional current agent identity for hosted MCP scope isolation
            session_id: Optional current conversation session identity for session-scoped isolation
        """
        user_entries = self._entries.get(user_id, {})
        if not user_entries:
            return False

        now = time.time()
        # Filter out expired time-bound scoped grants opportunistically
        entries = [e for e in user_entries.values() if e.expires_at is None or e.expires_at > now]
        if len(entries) != len(user_entries):
            # Prune expired entries from in-memory cache
            self._entries[user_id] = {
                (e.permission, e.tool_name, e.tool_args_hash, e.command_pattern, e.agent_id, e.session_id): e
                for e in entries
            }
        if not entries:
            return False

        # Helper to check if entry agent_id and session_id are compatible with current caller
        def _scope_matches(entry: AllowlistEntry) -> bool:
            if entry.session_id:
                if not session_id or entry.session_id.strip() != session_id.strip():
                    return False
            if entry.agent_id:
                return bool(agent_id and entry.agent_id.strip() == agent_id.strip())
            return True

        for entry in entries:
            if (
                entry.permission == permission_type
                and entry.tool_name == tool_name
                and entry.tool_args_hash is not None
                and entry.command_pattern is None
                and entry.tool_args_hash == tool_args_hash
                and _scope_matches(entry)
            ):
                return True

        if command:
            for entry in entries:
                if (
                    entry.permission == permission_type
                    and entry.tool_name == tool_name
                    and entry.command_pattern is not None
                    and matches_command_pattern(entry.command_pattern, command)
                    and _scope_matches(entry)
                ):
                    return True

        for entry in entries:
            if (
                entry.permission == permission_type
                and entry.tool_name == tool_name
                and entry.tool_args_hash is None
                and entry.command_pattern is None
                and _scope_matches(entry)
            ):
                return True

        return any(
            entry.permission == permission_type
            and entry.tool_name is None
            and _scope_matches(entry)
            for entry in entries
        )

    async def add(self, user_id: str, entry: AllowlistEntry) -> None:
        """Add an allow-always entry for a user (concurrent-safe).

        Physical Security Invariant:
        Entries with a non-None session_id are in-memory session-scoped grants.
        They MUST NEVER be persisted to the permanent store.
        """
        # Ensure lock exists
        async with self._meta_lock:
            _, lock, is_new = self._get_or_create_lock(user_id)
            if is_new:
                self._cache_meta[user_id] = (time.time(), lock)

        # Protect write with per-user lock
        async with lock:
            if user_id not in self._entries:
                self._entries[user_id] = {}
            key = (entry.permission, entry.tool_name, entry.tool_args_hash, entry.command_pattern, entry.agent_id, entry.session_id)

            if key in self._entries[user_id]:
                return

            self._entries[user_id][key] = entry
            self._cache_meta[user_id] = (time.time(), lock)

        # Do NOT persist session-scoped grants to disk/DB!
        if self._store and entry.session_id is None:
            await self._store.save(user_id, entry)
        logger.info(
            "[ALLOWLIST] Added (%s, tool=%s, args_hash=%s, pattern=%s, agent=%s, session=%s, expires_at=%s) for user %s",
            entry.permission,
            entry.tool_name,
            entry.tool_args_hash,
            entry.command_pattern,
            entry.agent_id,
            entry.session_id,
            entry.expires_at,
            user_id,
        )

    async def remove(
        self,
        user_id: str,
        permission: str,
        tool_name: str | None = None,
        tool_args_hash: str | None = None,
        command_pattern: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Remove an allow-always entry (concurrent-safe)."""
        if user_id in self._cache_meta:
            _, lock = self._cache_meta[user_id]
            async with lock:
                user_entries = self._entries.get(user_id, {})
                keys_to_remove = [
                    key
                    for key, entry in user_entries.items()
                    if entry.permission == permission
                    and (tool_name is None or entry.tool_name == tool_name)
                    and (tool_args_hash is None or entry.tool_args_hash == tool_args_hash)
                    and (command_pattern is None or entry.command_pattern == command_pattern)
                    and (agent_id is None or entry.agent_id == agent_id)
                    and (session_id is None or entry.session_id == session_id)
                ]
                for key in keys_to_remove:
                    user_entries.pop(key, None)

        if self._store and session_id is None:
            await self._store.remove(user_id, permission, tool_name, tool_args_hash, command_pattern, agent_id)

    async def clear_session(self, user_id: str, session_id: str) -> int:
        """Clear all session-scoped allowlist entries for a specific conversation session."""
        if not session_id or user_id not in self._entries:
            return 0
        async with self._meta_lock:
            _, lock, is_new = self._get_or_create_lock(user_id)
            if is_new:
                self._cache_meta[user_id] = (time.time(), lock)

        cleared_count = 0
        async with lock:
            user_entries = self._entries.get(user_id, {})
            keys_to_remove = [k for k, e in user_entries.items() if e.session_id == session_id]
            for k in keys_to_remove:
                user_entries.pop(k, None)
                cleared_count += 1
        if cleared_count > 0:
            logger.info("[ALLOWLIST] Cleared %d session-scoped entries for session %s (user %s)", cleared_count, session_id, user_id)
        return cleared_count

        if self._store:
            await self._store.remove(user_id, permission, tool_name, tool_args_hash, command_pattern, agent_id)

    async def list_active_grants(self, user_id: str) -> list[AllowlistEntry]:
        """Return all currently active allowlist entries for a user, filtering expired grants."""
        await self.load_user(user_id)
        now = time.time()
        user_entries = self._entries.get(user_id, {})
        active = [e for e in user_entries.values() if e.expires_at is None or e.expires_at > now]
        if len(active) != len(user_entries):
            self._entries[user_id] = {
                (e.permission, e.tool_name, e.tool_args_hash, e.command_pattern, e.agent_id): e
                for e in active
            }
        return active

    async def clear_user(self, user_id: str) -> int:
        """Clear all allowlist entries for a user (concurrent-safe).

        Args:
            user_id: User identifier

        Returns:
            Number of entries cleared
        """
        entries_to_clear = []
        if user_id in self._entries:
            entries_to_clear = list(self._entries[user_id].values())

        for entry in entries_to_clear:
            await self.remove(
                user_id,
                entry.permission,
                entry.tool_name,
                entry.tool_args_hash,
                entry.command_pattern,
                entry.agent_id,
            )

        return len(entries_to_clear)


# Module-level singleton
_allowlist: Allowlist | None = None


def get_allowlist() -> Allowlist:
    """Get the global Allowlist instance."""
    global _allowlist
    if _allowlist is None:
        _allowlist = Allowlist()
    return _allowlist


def set_allowlist_store(store: AllowlistStore) -> None:
    """Configure the persistent backend for the global Allowlist.

    Should be called once at app startup to inject DB/file store.
    """
    global _allowlist
    _allowlist = Allowlist(store=store)
