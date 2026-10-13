"""Guard against flipping ephemeral delta SQLite path while session buffers are hot."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.ephemeral_delta.models import (
    DeltaActionKind,
    EphemeralDeltaItem,
)
from myrm_agent_harness.toolkits.memory.ephemeral_delta.shared_store import (
    configure_ephemeral_delta_persistence,
    get_shared_ephemeral_delta_store,
    reset_shared_ephemeral_delta_store_for_tests,
)


def test_configure_refuses_db_path_switch_when_buffers_nonempty(tmp_path: Path) -> None:
    reset_shared_ephemeral_delta_store_for_tests()
    db_a = tmp_path / "a" / "memory.db"
    db_b = tmp_path / "b" / "memory.db"
    session_id = "chat-guard-1"

    configure_ephemeral_delta_persistence(db_a)
    store = get_shared_ephemeral_delta_store()
    store.record_delta(
        session_id,
        EphemeralDeltaItem(
            delta_id="delta_guard_1",
            target_key="profile:nickname",
            content="GuardNick",
            action=DeltaActionKind.OVERRIDE,
            turn_index=1,
            source="memory_write",
        ),
    )

    configure_ephemeral_delta_persistence(db_b)
    assert store is get_shared_ephemeral_delta_store()
    assert store.get_active_deltas(session_id)[0].content == "GuardNick"

    reset_shared_ephemeral_delta_store_for_tests()


def test_configure_allows_db_path_switch_when_buffers_empty(tmp_path: Path) -> None:
    reset_shared_ephemeral_delta_store_for_tests()
    db_a = tmp_path / "a" / "memory.db"
    db_b = tmp_path / "b" / "memory.db"

    configure_ephemeral_delta_persistence(db_a)
    configure_ephemeral_delta_persistence(db_b)
    store = get_shared_ephemeral_delta_store()
    assert store.get_active_deltas("unused") == []

    reset_shared_ephemeral_delta_store_for_tests()
