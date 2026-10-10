"""Core engine implementing safe episodic memory forgetting.

[INPUT]
- SqliteEpisodicMemoryStore, TransactionHookManager, and ForgetRequest specifications.

[OUTPUT]
- SafeEpisodicForgetEngine delivering authorization-gated forgetting with shared child retention.

[POS]
- Core domain engine for Item 149 SafeEpisodicForgetSuite.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable

from .models import (
    ForgetRequest,
    InvalidationEvent,
    MemoryTier,
    ParentProbeResult,
    SafeForgetResult,
)
from .sqlite_adapter import SqliteEpisodicMemoryStore
from .transaction_hooks import TransactionHookManager

logger = logging.getLogger(__name__)


class SafeEpisodicForgetEngine:
    """Orchestrates atomic episodic forgetting with cross-tier parent retention.

    Core capabilities:
    1. Authorization predicate: enforces caller session boundary or global scope.
    2. Shared child retention: preserves annotations, embeddings, and gists when a
       competing working or legacy parent shares the memory ID.
    3. Atomicity: combines parent probing and cascading within an immediate write lock.
    4. After-commit event dispatch: guarantees invalidation hooks fire only upon commit.
    """

    SHARED_CHILD_TABLES: tuple[str, ...] = ("annotations", "memory_embeddings", "gists")

    def __init__(
        self,
        store: SqliteEpisodicMemoryStore,
        hook_manager: TransactionHookManager | None = None,
    ) -> None:
        self._store = store
        self._hook_manager = hook_manager or TransactionHookManager()
        self._event_listeners: list[Callable[[InvalidationEvent], None]] = []

    @property
    def hook_manager(self) -> TransactionHookManager:
        """Return the transaction hook manager attached to this engine."""
        return self._hook_manager

    def add_event_listener(self, listener: Callable[[InvalidationEvent], None]) -> None:
        """Register a callback for memory invalidation events."""
        self._event_listeners.append(listener)

    def probe_parents(
        self,
        memory_id: str,
        caller_session_id: str,
        conn: sqlite3.Connection,
        allow_global: bool = True,
    ) -> ParentProbeResult:
        """Probe authorized episodic row and identify competing parent tiers under lock."""
        cur = conn.cursor()

        # Check authorized episodic presence
        cur.execute(
            "SELECT id, session_id, scope FROM episodic_memory WHERE id = ?",
            (memory_id,),
        )
        row = cur.fetchone()
        if row is None:
            return ParentProbeResult(
                memory_id=memory_id,
                authorized=False,
                episodic_exists=False,
                competing_tiers=(),
            )

        row_session = str(row["session_id"])
        row_scope = str(row["scope"])
        authorized = (row_session == caller_session_id) or (allow_global and row_scope == "global")

        competing: list[MemoryTier] = []
        # Probe working memory tier
        cur.execute("SELECT 1 FROM working_memory WHERE id = ? LIMIT 1", (memory_id,))
        if cur.fetchone() is not None:
            competing.append(MemoryTier.WORKING)

        # Probe legacy memories tier
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memories'",
        )
        if cur.fetchone() is not None:
            cur.execute("SELECT 1 FROM memories WHERE id = ? LIMIT 1", (memory_id,))
            if cur.fetchone() is not None:
                competing.append(MemoryTier.LEGACY)

        return ParentProbeResult(
            memory_id=memory_id,
            authorized=authorized,
            episodic_exists=True,
            competing_tiers=tuple(competing),
        )

    def forget_episodic(
        self,
        request: ForgetRequest,
        conn: sqlite3.Connection | None = None,
    ) -> SafeForgetResult:
        """Safely forget an episodic memory under authorization and cross-tier guards."""
        target_conn = conn or self._store.get_connection()
        owns_transaction = not target_conn.in_transaction

        if owns_transaction:
            target_conn.execute("BEGIN IMMEDIATE")

        try:
            probe = self.probe_parents(
                request.memory_id,
                request.caller_session_id,
                target_conn,
                allow_global=request.allow_global,
            )

            if not probe.episodic_exists:
                if owns_transaction:
                    target_conn.execute("COMMIT")
                return SafeForgetResult(
                    memory_id=request.memory_id,
                    deleted=False,
                    unauthorized=False,
                    retained_shared_children=False,
                    deleted_child_tables=(),
                    message="Episodic memory does not exist.",
                )

            if not probe.authorized:
                if owns_transaction:
                    target_conn.execute("COMMIT")
                return SafeForgetResult(
                    memory_id=request.memory_id,
                    deleted=False,
                    unauthorized=True,
                    retained_shared_children=False,
                    deleted_child_tables=(),
                    message="Unauthorized: session mismatch and memory scope is not global.",
                )

            cur = target_conn.cursor()
            # 1. Delete episodic vector entry
            cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'vec_episodes'",
            )
            if cur.fetchone() is not None:
                cur.execute("DELETE FROM vec_episodes WHERE memory_id = ?", (request.memory_id,))

            # 2. Delete authorized episodic row
            cur.execute(
                "DELETE FROM episodic_memory WHERE id = ? AND (session_id = ? OR (scope = 'global' AND ?))",
                (request.memory_id, request.caller_session_id, 1 if request.allow_global else 0),
            )
            deleted_count = cur.rowcount

            # 3. Handle shared children: retain if competing parents survive
            deleted_tables: list[str] = []
            retained_children = probe.has_competing_parents

            if deleted_count > 0 and not retained_children:
                for child_table in self.SHARED_CHILD_TABLES:
                    cur.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (child_table,),
                    )
                    if cur.fetchone() is not None:
                        cur.execute(
                            f"DELETE FROM {child_table} WHERE memory_id = ?",
                            (request.memory_id,),
                        )
                        if cur.rowcount > 0:
                            deleted_tables.append(child_table)

            # 4. Queue or dispatch after-commit invalidation event
            event = InvalidationEvent(
                event_name="MEMORY_INVALIDATED",
                memory_id=request.memory_id,
                tier=MemoryTier.EPISODIC.value,
                timestamp=time.time(),
                metadata={"reason": request.reason, "session_id": request.caller_session_id},
            )

            def _emit_hook() -> None:
                for listener in self._event_listeners:
                    try:
                        listener(event)
                    except Exception as err:
                        logger.error("Error in invalidation listener: %s", err)

            self._hook_manager.queue_after_commit(_emit_hook)

            if owns_transaction:
                target_conn.execute("COMMIT")
                self._hook_manager.on_commit()

            return SafeForgetResult(
                memory_id=request.memory_id,
                deleted=deleted_count > 0,
                unauthorized=False,
                retained_shared_children=retained_children,
                deleted_child_tables=tuple(deleted_tables),
                message="Successfully deleted episodic memory with safe retention semantics.",
            )

        except Exception as exc:
            if owns_transaction:
                target_conn.execute("ROLLBACK")
                self._hook_manager.on_rollback()
            raise exc
