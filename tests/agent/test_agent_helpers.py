import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, create_autospec, patch

import pytest

from myrm_agent_harness.agent._internals._agent_helpers import schedule_post_run_idle_tasks
from myrm_agent_harness.agent.background_worker import registry as registry_module
from myrm_agent_harness.agent.background_worker.registry import IdleTaskRegistry, get_idle_task_registry
from myrm_agent_harness.agent.event_log.backends import FileEventLogBackend
from myrm_agent_harness.agent.event_log.logger import EventLogger
from myrm_agent_harness.agent.middlewares._session_context import set_event_logger

_CONTEXT = {"session_id": "chat_real", "workspace_root": "/tmp/test", "chat_id": "real", "agent_id": "agent-1"}


@pytest.fixture(autouse=True)
def _no_event_logger():
    set_event_logger(None)
    yield
    set_event_logger(None)


def _enqueued_types(registry: IdleTaskRegistry) -> set[str]:
    return {call[0][1] for call in registry.enqueue.call_args_list}


def _schedule_with_mock_registry(context: dict[str, object]) -> tuple[IdleTaskRegistry, AsyncMock]:
    """Autospec'd registry: a drifted ``enqueue`` call signature fails instead of being swallowed by a bare mock."""
    registry = create_autospec(IdleTaskRegistry, instance=True)
    with (
        patch("myrm_agent_harness.agent._internals._agent_helpers._fire_and_forget"),
        patch("myrm_agent_harness.agent.background_worker.registry.get_idle_task_registry", return_value=registry),
        patch("myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task") as schedule,
    ):
        schedule_post_run_idle_tasks(context)
    return registry, schedule


def test_run_without_an_event_logger_skips_evidence_extraction():
    registry, schedule = _schedule_with_mock_registry(_CONTEXT)

    assert _enqueued_types(registry) == {"cognitive_consolidation", "context_compaction"}
    schedule.assert_called_once()


def test_run_with_an_event_logger_enqueues_evidence_extraction_for_the_chat(tmp_path: Path):
    backend = FileEventLogBackend(log_dir=tmp_path, session_id="real")
    set_event_logger(EventLogger(session_id="chat_real", backend=backend, storage_key="real"))

    registry, _ = _schedule_with_mock_registry(_CONTEXT)

    evidence = [c for c in registry.enqueue.call_args_list if c[0][1] == "session_evidence_extraction"]
    assert len(evidence) == 1
    assert evidence[0][0][2] == {"chat_id": "real", "agent_id": "agent-1"}


def test_run_without_chat_id_only_enqueues_consolidation():
    registry, _ = _schedule_with_mock_registry({"session_id": "s", "workspace_root": "/tmp/test"})

    assert _enqueued_types(registry) == {"cognitive_consolidation"}


def test_run_without_session_or_workspace_schedules_nothing():
    registry, schedule = _schedule_with_mock_registry({"chat_id": "real"})

    registry.enqueue.assert_not_called()
    schedule.assert_not_called()


def test_schedule_post_run_idle_tasks_persists_runnable_tasks_in_real_registry(tmp_path: Path, monkeypatch):
    """End-to-end against the real SQLite registry: tasks are enqueued and can be acquired by session id."""
    monkeypatch.setattr(registry_module, "_registry_instance", None)
    set_event_logger(
        EventLogger(
            session_id="chat_real", backend=FileEventLogBackend(log_dir=tmp_path, session_id="real"), storage_key="real"
        )
    )

    async def scenario() -> list[str]:
        with patch("myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task"):
            schedule_post_run_idle_tasks({**_CONTEXT, "workspace_root": str(tmp_path)})
            await asyncio.sleep(0.3)
        registry = get_idle_task_registry(str(tmp_path))
        acquired: list[str] = []
        while (record := await registry.acquire_next("chat_real")) is not None:
            acquired.append(record.task_type)
        return acquired

    acquired = asyncio.run(scenario())

    assert set(acquired) == {"cognitive_consolidation", "session_evidence_extraction", "context_compaction"}


def test_init_usage_ledger_attaches_ledger(tmp_path):
    from myrm_agent_harness.agent._internals._agent_helpers import init_usage_ledger
    from myrm_agent_harness.utils.token_economics.tracker import get_usage_ledger

    init_usage_ledger({"workspace_path": str(tmp_path)})

    assert get_usage_ledger() is not None


def test_init_usage_ledger_noop_without_workspace_path():
    from myrm_agent_harness.agent._internals._agent_helpers import init_usage_ledger

    init_usage_ledger(None)
    init_usage_ledger({})
    init_usage_ledger({"workspace_path": ""})
