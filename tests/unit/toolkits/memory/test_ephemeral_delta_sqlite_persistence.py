"""Restart-safe ephemeral delta persistence on memory.db."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.ephemeral_delta.delta_store import (
    EphemeralDeltaStore,
)
from myrm_agent_harness.toolkits.memory.ephemeral_delta.models import (
    DeltaActionKind,
    EphemeralDeltaItem,
)
from myrm_agent_harness.toolkits.memory.ephemeral_delta.sqlite_persistence import (
    EphemeralDeltaSqlitePersistence,
)


def test_sqlite_persistence_survives_store_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    persistence = EphemeralDeltaSqlitePersistence(db_path)
    session_id = "chat-restart-01"

    writer = EphemeralDeltaStore(persistence=persistence)
    item = EphemeralDeltaItem(
        delta_id="delta_restart_1",
        target_key="profile:nickname",
        content="Sam",
        action=DeltaActionKind.OVERRIDE,
        turn_index=2,
        source="memory_write",
    )
    writer.record_delta(session_id, item)
    assert writer.get_active_deltas(session_id)[0].content == "Sam"

    reader = EphemeralDeltaStore(persistence=persistence)
    reader.ensure_hydrated(session_id)
    active = reader.get_active_deltas(session_id)
    assert len(active) == 1
    assert active[0].target_key == "profile:nickname"
    assert active[0].content == "Sam"

    writer.clear(session_id)
    reader_after_clear = EphemeralDeltaStore(persistence=persistence)
    reader_after_clear.ensure_hydrated(session_id)
    assert reader_after_clear.get_active_deltas(session_id) == []
