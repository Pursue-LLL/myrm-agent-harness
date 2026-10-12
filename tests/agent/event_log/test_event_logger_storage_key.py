"""EventLogger exposes the backend's storage key, separate from the runtime session id."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.event_log.backends import FileEventLogBackend
from myrm_agent_harness.agent.event_log.logger import EventLogger

_CHAT_ID = "42"
_SESSION_ID = f"chat_{_CHAT_ID}"


@pytest.mark.asyncio
async def test_storage_key_defaults_to_the_session_id(tmp_path: Path) -> None:
    logger = EventLogger(FileEventLogBackend(log_dir=tmp_path, session_id="s1"), "s1")

    assert logger.storage_key == "s1"


@pytest.mark.asyncio
async def test_events_are_stamped_with_the_session_id_and_filed_under_the_storage_key(tmp_path: Path) -> None:
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=_CHAT_ID)
    logger = EventLogger(backend, _SESSION_ID, storage_key=_CHAT_ID)

    await logger.start()
    await logger.close()

    events = await backend.get_events(logger.storage_key)
    assert {e.session_id for e in events} == {_SESSION_ID}
    assert (tmp_path / f"{_CHAT_ID}.jsonl").exists()


@pytest.mark.asyncio
async def test_close_does_not_re_read_the_log(tmp_path: Path) -> None:
    """Closing sits on the user-visible path; it must not rescan the chat's accumulated log."""
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=_CHAT_ID)
    backend.get_events = AsyncMock(wraps=backend.get_events)
    logger = EventLogger(backend, _SESSION_ID, storage_key=_CHAT_ID)

    await logger.start()
    await logger.close()

    backend.get_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_started_at_is_floored_to_the_persisted_millisecond(tmp_path: Path) -> None:
    """Persisted timestamps are rounded to ms; a turn-scoped read must still include session_start."""
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=_CHAT_ID)
    logger = EventLogger(backend, _SESSION_ID, storage_key=_CHAT_ID)

    await logger.start()
    await logger.close()

    events = await backend.get_events(logger.storage_key)
    assert min(e.timestamp for e in events) >= logger.started_at
