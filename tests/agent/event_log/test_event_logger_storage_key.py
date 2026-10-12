"""EventLogger read-backs use the backend's storage key, not the runtime session id."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.event_log.backends import FileEventLogBackend
from myrm_agent_harness.agent.event_log.logger import EventLogger

_CHAT_ID = "42"
_SESSION_ID = f"chat_{_CHAT_ID}"


@pytest.mark.asyncio
async def test_close_time_integrity_gate_reads_the_storage_key(tmp_path: Path) -> None:
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=_CHAT_ID)
    backend.get_events = AsyncMock(wraps=backend.get_events)
    logger = EventLogger(backend, _SESSION_ID, storage_key=_CHAT_ID)

    await logger.start()
    await logger.close()

    backend.get_events.assert_awaited_once_with(_CHAT_ID)
    assert (tmp_path / f"{_CHAT_ID}.jsonl").exists()


@pytest.mark.asyncio
async def test_storage_key_defaults_to_the_session_id(tmp_path: Path) -> None:
    logger = EventLogger(FileEventLogBackend(log_dir=tmp_path, session_id="s1"), "s1")

    assert logger.storage_key == "s1"


@pytest.mark.asyncio
async def test_gate_failure_is_reported_as_a_warning_not_swallowed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=_CHAT_ID)
    backend.get_events = AsyncMock(side_effect=RuntimeError("disk gone"))
    logger = EventLogger(backend, _SESSION_ID, storage_key=_CHAT_ID)
    await logger.start()

    with caplog.at_level(logging.WARNING):
        await logger.close()

    assert any(
        r.levelno == logging.WARNING and "integrity gate verification failed" in r.getMessage() for r in caplog.records
    )
