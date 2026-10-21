"""Process-wide ephemeral delta store (single shared instance).

[INPUT]
- toolkits.memory.ephemeral_delta.delta_store::EphemeralDeltaStore (POS: In-memory, session-scoped transient buffer for prompt-cache-preserving deltas)
- toolkits.memory.ephemeral_delta.sqlite_persistence::EphemeralDeltaSqlitePersistence (POS: Same DB file as relational memory store; survives process restart within a chat session)

[OUTPUT]
- configure_ephemeral_delta_persistence: wire SQLite backend to the shared store
- ensure_ephemeral_deltas_hydrated: reload session deltas after process restart
- get_shared_ephemeral_delta_store: singleton EphemeralDeltaStore for agent turns and server bridge

[POS]
Single store instance so server EphemeralDeltaService and live agent middleware share session deltas.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from myrm_agent_harness.toolkits.memory.ephemeral_delta.delta_store import (
    EphemeralDeltaStore,
)
from myrm_agent_harness.toolkits.memory.ephemeral_delta.sqlite_persistence import (
    EphemeralDeltaSqlitePersistence,
)

logger = logging.getLogger(__name__)

_store_lock = threading.Lock()
_store: EphemeralDeltaStore | None = None
_persistence: EphemeralDeltaSqlitePersistence | None = None
_configured_db_path: str | None = None


def configure_ephemeral_delta_persistence(db_path: str | Path) -> None:
    """Attach Volume-backed SQLite persistence to the process-wide ephemeral delta store."""
    global _store, _persistence, _configured_db_path
    normalized = str(Path(db_path).expanduser().resolve())
    with _store_lock:
        if _configured_db_path == normalized and _persistence is not None:
            return
        if (
            _configured_db_path is not None
            and _configured_db_path != normalized
            and _store is not None
            and _store.has_in_memory_buffers()
        ):
            logger.warning(
                "Refusing ephemeral delta persistence reconfigure from %s to %s "
                "while in-memory session buffers are non-empty",
                _configured_db_path,
                normalized,
            )
            return
        _persistence = EphemeralDeltaSqlitePersistence(normalized)
        _configured_db_path = normalized
        if _store is None:
            _store = EphemeralDeltaStore(persistence=_persistence)
        else:
            _store.attach_persistence(_persistence)


def get_shared_ephemeral_delta_store() -> EphemeralDeltaStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = EphemeralDeltaStore(persistence=_persistence)
        return _store


def ensure_ephemeral_deltas_hydrated(session_id: str) -> None:
    """Load persisted deltas for a chat session when the in-memory buffer is cold."""
    normalized = (session_id or "").strip()
    if not normalized:
        return
    get_shared_ephemeral_delta_store().ensure_hydrated(normalized)


def reset_shared_ephemeral_delta_store_for_tests() -> None:
    """Clear singleton state (unit tests only)."""
    global _store, _persistence, _configured_db_path
    with _store_lock:
        _store = None
        _persistence = None
        _configured_db_path = None
