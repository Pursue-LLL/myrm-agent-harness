"""Session evidence extraction against a real per-chat FileEventLogBackend (no mocked event log)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.agent.background_worker.registry import IdleTaskRecord
from myrm_agent_harness.agent.background_worker.session_evidence_task import (
    register_skill_store_provider,
    run_session_evidence_extraction,
)
from myrm_agent_harness.agent.event_log.backends import FileEventLogBackend
from myrm_agent_harness.agent.event_log.logger import EventLogger
from myrm_agent_harness.agent.middlewares._session_context import set_event_logger

_CHAT_ID = "42"
_RUNTIME_SESSION_ID = f"chat_{_CHAT_ID}"
_MODULE = "myrm_agent_harness.agent.background_worker.session_evidence_task"
_real_sleep = asyncio.sleep


def _task() -> IdleTaskRecord:
    return IdleTaskRecord(
        id=1,
        session_id=_RUNTIME_SESSION_ID,
        task_type="session_evidence_extraction",
        payload={"agent_id": "agent_1", "chat_id": _CHAT_ID},
        status="running",
        created_at=0.0,
    )


@pytest.fixture(autouse=True)
def _reset_runtime_bindings():
    set_event_logger(None)
    register_skill_store_provider(None)
    yield
    set_event_logger(None)
    register_skill_store_provider(None)


async def _closed_turn_log(tmp_path: Path, *, failures: bool) -> EventLogger:
    """Mirror the host wiring: per-chat file backend keyed by chat id, events stamped with the runtime session id."""
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=_CHAT_ID)
    logger = EventLogger(backend, _RUNTIME_SESSION_ID, storage_key=_CHAT_ID)
    await logger.start()
    if failures:
        await logger.log("tool_failure", {"tool_name": "bash", "error": "command not found: foo"})
    await logger.close()
    set_event_logger(logger)
    return logger


@pytest.mark.asyncio
async def test_skips_without_an_event_logger() -> None:
    result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result == {"skipped": True, "reason": "No EventLogger configured"}


@pytest.mark.asyncio
async def test_finds_failures_in_the_log_filed_under_the_chat_id(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failures=True)

    with patch(f"{_MODULE}._capture_skill_proposal", new_callable=AsyncMock, return_value=None) as capture:
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert (tmp_path / f"{_CHAT_ID}.jsonl").exists()
    assert result["extracted"] is True
    assert result["anti_patterns_count"] == 1
    capture.assert_awaited_once()


@pytest.mark.asyncio
async def test_clean_turn_yields_no_proposal(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failures=False)

    with patch(f"{_MODULE}._capture_skill_proposal", new_callable=AsyncMock) as capture:
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["anti_patterns_count"] == 0
    assert result["proposal"] is None
    capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_proposal_is_drafted_from_the_stored_trajectory(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failures=True)
    proposal = MagicMock(skill_id="shell_pitfalls", reasoning="why", proposed_content="# body", score=0.8)
    engine = MagicMock()
    engine.capture_skill_from_trajectory = AsyncMock(return_value=proposal)
    manager = MagicMock()
    manager._consolidation_llm = MagicMock(spec=BaseChatModel)
    host_store = MagicMock()
    register_skill_store_provider(lambda: host_store)

    with (
        patch(f"{_MODULE}.get_memory_manager", return_value=manager),
        patch(
            "myrm_agent_harness.agent.skills.evolution.core.engine.SkillEvolutionEngine", return_value=engine
        ) as engine_cls,
    ):
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert engine_cls.call_args.kwargs["store"] is host_store
    host_store.close.assert_not_called()
    trajectory = engine.capture_skill_from_trajectory.await_args.kwargs["trajectory"]
    assert "command not found: foo" in trajectory
    assert result["proposal"] == {
        "skill_id": "shell_pitfalls",
        "reasoning": "why",
        "proposed_content": "# body",
        "score": 0.8,
        "agent_id": "agent_1",
        "chat_id": _CHAT_ID,
    }


@pytest.mark.asyncio
async def test_missing_consolidation_llm_yields_no_proposal(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failures=True)
    manager = MagicMock()
    manager._consolidation_llm = None
    register_skill_store_provider(MagicMock)

    with patch(f"{_MODULE}.get_memory_manager", return_value=manager):
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["anti_patterns_count"] == 1
    assert result["proposal"] is None


@pytest.mark.asyncio
async def test_without_a_skill_store_provider_no_proposal_is_drafted(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failures=True)
    manager = MagicMock()
    manager._consolidation_llm = MagicMock(spec=BaseChatModel)

    with patch(f"{_MODULE}.get_memory_manager", return_value=manager):
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["anti_patterns_count"] == 1
    assert result["proposal"] is None


@pytest.mark.asyncio
async def test_a_finished_turn_surfaces_a_proposal_through_the_idle_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whole chain on real parts: run end -> enqueue -> idle window -> event log read -> completion event."""
    from myrm_agent_harness.agent._internals._agent_helpers import schedule_post_run_idle_tasks
    from myrm_agent_harness.agent.background_worker import idle_tasks
    from myrm_agent_harness.agent.background_worker import registry as registry_module
    from myrm_agent_harness.runtime.maintenance.protocols import CapacityTicket

    monkeypatch.setattr(registry_module, "_registry_instance", None)
    monkeypatch.setattr(idle_tasks.asyncio, "sleep", AsyncMock())
    scheduler = AsyncMock()
    scheduler.report_outcome = MagicMock()
    scheduler.request_capacity.return_value = CapacityTicket(ticket_id="t", task_type="probe")
    event_bus = MagicMock()
    monkeypatch.setattr(idle_tasks, "get_maintenance_scheduler", lambda: scheduler)
    monkeypatch.setattr(idle_tasks, "get_event_bus", lambda: event_bus)
    monkeypatch.setattr(idle_tasks, "get_memory_manager", lambda: None)

    await _closed_turn_log(tmp_path, failures=True)
    proposal = MagicMock(skill_id="shell_pitfalls", reasoning="why", proposed_content="# body", score=0.8)
    engine = MagicMock()
    engine.capture_skill_from_trajectory = AsyncMock(return_value=proposal)
    manager = MagicMock()
    manager._consolidation_llm = MagicMock(spec=BaseChatModel)
    register_skill_store_provider(MagicMock)

    with patch("myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task") as schedule:
        schedule_post_run_idle_tasks(
            {"session_id": _RUNTIME_SESSION_ID, "workspace_root": str(tmp_path), "chat_id": _CHAT_ID}
        )
        await _real_sleep(0.3)
    window = schedule.call_args.args[1]

    with (
        patch(f"{_MODULE}.get_memory_manager", return_value=manager),
        patch("myrm_agent_harness.agent.skills.evolution.core.engine.SkillEvolutionEngine", return_value=engine),
    ):
        await window()

    completed = [e for e in (c.args[0] for c in event_bus.publish.call_args_list) if e.status == "completed"]
    evidence = next(e for e in completed if e.task_name == "session_evidence_extraction")
    assert evidence.session_id == _RUNTIME_SESSION_ID
    assert evidence.data["proposal"]["skill_id"] == "shell_pitfalls"
    assert {e.task_name for e in completed} == {
        "cognitive_consolidation",
        "session_evidence_extraction",
        "context_compaction",
    }
