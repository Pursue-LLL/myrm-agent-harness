"""Unit tests for Item 149 SafeEpisodicForgetSuite.

Tests authorization predicates, cross-tier shared child retention, immediate write locks,
and after-commit invalidation event emission with savepoint support.
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.safe_episodic_forget import (
    ForgetRequest,
    InvalidationEvent,
    MemoryTier,
    SafeEpisodicForgetEngine,
    SqliteEpisodicMemoryStore,
    TransactionHookManager,
)


def _seed_episodic_memory(
    store: SqliteEpisodicMemoryStore,
    memory_id: str,
    session_id: str,
    scope: str = "session",
    content: str = "Episodic content",
) -> None:
    conn = store.get_connection()
    conn.execute(
        "INSERT INTO episodic_memory (id, session_id, scope, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (memory_id, session_id, scope, content, time.time()),
    )
    conn.execute(
        "INSERT INTO vec_episodes (id, memory_id, embedding) VALUES (?, ?, ?)",
        (f"vec_{memory_id}", memory_id, b"\x00\x01\x02"),
    )


def _seed_children(
    store: SqliteEpisodicMemoryStore,
    memory_id: str,
) -> None:
    conn = store.get_connection()
    conn.execute(
        "INSERT INTO annotations (id, memory_id, note) VALUES (?, ?, ?)",
        (f"ann_{memory_id}", memory_id, "User note"),
    )
    conn.execute(
        "INSERT INTO memory_embeddings (id, memory_id, embedding_json) VALUES (?, ?, ?)",
        (f"emb_{memory_id}", memory_id, "[0.1, 0.2, 0.3]"),
    )
    conn.execute(
        "INSERT INTO gists (id, memory_id, gist) VALUES (?, ?, ?)",
        (f"gist_{memory_id}", memory_id, "Summary gist"),
    )


def test_authorization_predicate_session_and_global() -> None:
    """Test that session match or global scope allows forget, while cross-session fails."""
    store = SqliteEpisodicMemoryStore(":memory:")
    engine = SafeEpisodicForgetEngine(store)

    # 1. Same session -> authorized & deleted
    _seed_episodic_memory(store, "m1", "session_101", "session")
    res1 = engine.forget_episodic(
        ForgetRequest(memory_id="m1", caller_session_id="session_101")
    )
    assert res1.deleted is True
    assert res1.unauthorized is False

    # 2. Cross session mismatch on session-scoped row -> unauthorized
    _seed_episodic_memory(store, "m2", "session_101", "session")
    res2 = engine.forget_episodic(
        ForgetRequest(memory_id="m2", caller_session_id="session_999")
    )
    assert res2.deleted is False
    assert res2.unauthorized is True

    # Confirm m2 survives
    cur = store.get_connection().cursor()
    cur.execute("SELECT COUNT(*) FROM episodic_memory WHERE id = 'm2'")
    assert cur.fetchone()[0] == 1

    # 3. Global scope with cross session caller -> authorized & deleted
    _seed_episodic_memory(store, "m3", "session_101", "global")
    res3 = engine.forget_episodic(
        ForgetRequest(
            memory_id="m3",
            caller_session_id="session_999",
            allow_global=True,
        )
    )
    assert res3.deleted is True
    assert res3.unauthorized is False


def test_cross_tier_shared_children_retention() -> None:
    """Retains annotations, embeddings, and gists when a working or legacy parent survives."""
    store = SqliteEpisodicMemoryStore(":memory:")
    engine = SafeEpisodicForgetEngine(store)
    conn = store.get_connection()

    # Seed episodic memory and children
    _seed_episodic_memory(store, "shared_mem", "session_alpha")
    _seed_children(store, "shared_mem")

    # Seed competing working memory parent with same ID
    conn.execute(
        "INSERT INTO working_memory (id, session_id, content, timestamp) VALUES (?, ?, ?, ?)",
        ("shared_mem", "session_alpha", "Working content", time.time()),
    )
    conn.commit()

    # Forget episodic: must delete episodic row but retain children
    res = engine.forget_episodic(
        ForgetRequest(memory_id="shared_mem", caller_session_id="session_alpha")
    )
    assert res.deleted is True
    assert res.retained_shared_children is True
    assert res.deleted_child_tables == ()

    # Verify episodic row deleted but children intact
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM episodic_memory WHERE id = 'shared_mem'")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM annotations WHERE memory_id = 'shared_mem'")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM memory_embeddings WHERE memory_id = 'shared_mem'")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM gists WHERE memory_id = 'shared_mem'")
    assert cur.fetchone()[0] == 1


def test_cascade_delete_children_when_no_competing_parents() -> None:
    """Cascades to child tables when no working or legacy parent exists."""
    store = SqliteEpisodicMemoryStore(":memory:")
    engine = SafeEpisodicForgetEngine(store)
    conn = store.get_connection()

    _seed_episodic_memory(store, "orphan_mem", "session_beta")
    _seed_children(store, "orphan_mem")

    res = engine.forget_episodic(
        ForgetRequest(memory_id="orphan_mem", caller_session_id="session_beta")
    )
    assert res.deleted is True
    assert res.retained_shared_children is False
    assert set(res.deleted_child_tables) == {"annotations", "memory_embeddings", "gists"}

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM episodic_memory WHERE id = 'orphan_mem'")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM annotations WHERE memory_id = 'orphan_mem'")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM memory_embeddings WHERE memory_id = 'orphan_mem'")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM gists WHERE memory_id = 'orphan_mem'")
    assert cur.fetchone()[0] == 0


def test_legacy_parent_preserves_shared_children() -> None:
    """Preserves shared children when legacy memories table holds the parent ID."""
    store = SqliteEpisodicMemoryStore(":memory:")
    engine = SafeEpisodicForgetEngine(store)
    conn = store.get_connection()

    _seed_episodic_memory(store, "legacy_mem", "session_gamma")
    _seed_children(store, "legacy_mem")
    conn.execute(
        "INSERT INTO memories (id, content) VALUES (?, ?)",
        ("legacy_mem", "Legacy content"),
    )
    conn.commit()

    res = engine.forget_episodic(
        ForgetRequest(memory_id="legacy_mem", caller_session_id="session_gamma")
    )
    assert res.deleted is True
    assert res.retained_shared_children is True

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM annotations WHERE memory_id = 'legacy_mem'")
    assert cur.fetchone()[0] == 1


def test_after_commit_event_dispatch_and_rollback_discard() -> None:
    """Invalidation events must not fire before commit, and must discard on rollback."""
    store = SqliteEpisodicMemoryStore(":memory:")
    hook_mgr = TransactionHookManager()
    engine = SafeEpisodicForgetEngine(store, hook_mgr)
    conn = store.get_connection()

    emitted_events: list[InvalidationEvent] = []
    engine.add_event_listener(lambda ev: emitted_events.append(ev))

    # Scenario 1: Uncommitted transaction holds events
    _seed_episodic_memory(store, "tx_mem1", "session_tx")
    conn.execute("BEGIN IMMEDIATE")
    res1 = engine.forget_episodic(
        ForgetRequest(memory_id="tx_mem1", caller_session_id="session_tx"),
        conn=conn,
    )
    assert res1.deleted is True
    assert len(emitted_events) == 0  # Not committed yet!

    # Explicit commit drains hooks
    conn.execute("COMMIT")
    hook_mgr.on_commit()
    assert len(emitted_events) == 1
    assert emitted_events[0].memory_id == "tx_mem1"
    assert emitted_events[0].event_name == "MEMORY_INVALIDATED"

    # Scenario 2: Rollback discards queued hooks
    _seed_episodic_memory(store, "tx_mem2", "session_tx")
    conn.execute("BEGIN IMMEDIATE")
    res2 = engine.forget_episodic(
        ForgetRequest(memory_id="tx_mem2", caller_session_id="session_tx"),
        conn=conn,
    )
    assert res2.deleted is True
    assert len(emitted_events) == 1

    conn.execute("ROLLBACK")
    hook_mgr.on_rollback()
    assert len(emitted_events) == 1  # Still 1, new event discarded!

    # Verify tx_mem2 was rolled back and still exists
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM episodic_memory WHERE id = 'tx_mem2'")
    assert cur.fetchone()[0] == 1


def test_savepoint_rollback_and_release_semantics() -> None:
    """Savepoint rollback discards only its local hooks; outer released savepoint emits on commit."""
    store = SqliteEpisodicMemoryStore(":memory:")
    hook_mgr = TransactionHookManager()
    engine = SafeEpisodicForgetEngine(store, hook_mgr)
    conn = store.get_connection()

    emitted_events: list[InvalidationEvent] = []
    engine.add_event_listener(lambda ev: emitted_events.append(ev))

    _seed_episodic_memory(store, "sp_mem1", "session_sp")
    _seed_episodic_memory(store, "sp_mem2", "session_sp")

    conn.execute("BEGIN IMMEDIATE")

    # Savepoint 1: keep
    conn.execute("SAVEPOINT sp1")
    hook_mgr.on_savepoint("sp1")
    engine.forget_episodic(
        ForgetRequest(memory_id="sp_mem1", caller_session_id="session_sp"),
        conn=conn,
    )
    conn.execute("RELEASE SAVEPOINT sp1")
    hook_mgr.on_release_savepoint("sp1")

    # Savepoint 2: rollback
    conn.execute("SAVEPOINT sp2")
    hook_mgr.on_savepoint("sp2")
    engine.forget_episodic(
        ForgetRequest(memory_id="sp_mem2", caller_session_id="session_sp"),
        conn=conn,
    )
    conn.execute("ROLLBACK TO SAVEPOINT sp2")
    hook_mgr.on_rollback_to_savepoint("sp2")
    conn.execute("RELEASE SAVEPOINT sp2")
    hook_mgr.on_release_savepoint("sp2")

    assert len(emitted_events) == 0

    conn.execute("COMMIT")
    hook_mgr.on_commit()

    # Only sp_mem1 should emit! sp_mem2 was rolled back in savepoint
    assert len(emitted_events) == 1
    assert emitted_events[0].memory_id == "sp_mem1"
