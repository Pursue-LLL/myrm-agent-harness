"""Session evidence extraction against a real per-chat FileEventLogBackend (no mocked event log).

Tool calls are logged the way the streaming layer persists them: ``tasks_steps`` events carrying ``tool_name``.
"""

import asyncio
import itertools
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.agent.background_worker.registry import IdleTaskRecord
from myrm_agent_harness.agent.background_worker.session_evidence_task import (
    _format_trajectory,
    register_skill_store_provider,
    run_session_evidence_extraction,
)
from myrm_agent_harness.agent.event_log.backends import FileEventLogBackend
from myrm_agent_harness.agent.event_log.logger import EventLogger
from myrm_agent_harness.agent.event_log.trace_types import ToolCallRecord
from myrm_agent_harness.agent.middlewares._session_context import set_event_logger

_CHAT_ID = "42"
_RUNTIME_SESSION_ID = f"chat_{_CHAT_ID}"
_MODULE = "myrm_agent_harness.agent.background_worker.session_evidence_task"
_MCP_ERROR = "ToolExecutionError: MCPError: MCP tool not found: 12306.mcp__12306__get_current_date_tool"
_call_ids = itertools.count(1)


def _task(**payload: object) -> IdleTaskRecord:
    return IdleTaskRecord(
        id=1,
        session_id=_RUNTIME_SESSION_ID,
        task_type="session_evidence_extraction",
        payload={"agent_id": "agent_1", "chat_id": _CHAT_ID, **payload},
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


async def _log_tool_call(
    logger: EventLogger, *, failed: bool, fault_side: str | None = "harness_tool", error: str = _MCP_ERROR
) -> None:
    tool_name = "bash_code_execute_tool"
    data: dict[str, object] = {
        "tool_name": tool_name,
        "tool_call_id": f"call_{next(_call_ids)}",
        "step_key": f"{tool_name}_tool_error" if failed else f"{tool_name}_tool_result",
        "status": "error" if failed else "completed",
    }
    if failed:
        data["error"] = error
        if fault_side:
            data["fault_side"] = fault_side
    await logger.log("tasks_steps", data)


def _logger_for(backend: FileEventLogBackend) -> EventLogger:
    """Mirror the host wiring: per-chat file backend keyed by chat id, events stamped with the runtime session id."""
    return EventLogger(backend, _RUNTIME_SESSION_ID, storage_key=_CHAT_ID)


async def _closed_turn_log(tmp_path: Path, *, failed: bool, fault_side: str | None = "harness_tool") -> EventLogger:
    logger = _logger_for(FileEventLogBackend(log_dir=tmp_path, session_id=_CHAT_ID))
    await logger.start()
    await _log_tool_call(logger, failed=failed, fault_side=fault_side)
    await logger.close()
    set_event_logger(logger)
    return logger


@pytest.mark.asyncio
async def test_skips_without_an_event_logger() -> None:
    result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result == {"skipped": True, "reason": "No EventLogger configured"}


@pytest.mark.asyncio
async def test_finds_failed_tool_calls_in_the_log_filed_under_the_chat_id(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failed=True)

    with patch(f"{_MODULE}._capture_skill_proposal", new_callable=AsyncMock, return_value=None) as capture:
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert (tmp_path / f"{_CHAT_ID}.jsonl").exists()
    assert result["failed_tool_calls"] == 1
    capture.assert_awaited_once()


@pytest.mark.asyncio
async def test_clean_turn_yields_no_proposal(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failed=False)

    with patch(f"{_MODULE}._capture_skill_proposal", new_callable=AsyncMock) as capture:
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["failed_tool_calls"] == 0
    assert result["proposal"] is None
    capture.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_side", ["env", "owner"])
async def test_environment_and_user_faults_are_not_skill_material(tmp_path: Path, fault_side: str) -> None:
    await _closed_turn_log(tmp_path, failed=True, fault_side=fault_side)

    with patch(f"{_MODULE}._capture_skill_proposal", new_callable=AsyncMock) as capture:
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["failed_tool_calls"] == 0
    capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_unattributed_failures_still_count(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failed=True, fault_side=None)

    with patch(f"{_MODULE}._capture_skill_proposal", new_callable=AsyncMock, return_value=None):
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["failed_tool_calls"] == 1


@pytest.mark.asyncio
async def test_proposal_is_drafted_from_the_stored_trajectory(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failed=True)
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
    assert "bash_code_execute_tool -> FAILED (harness_tool)" in trajectory
    assert "MCP tool not found" in trajectory
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
    await _closed_turn_log(tmp_path, failed=True)
    manager = MagicMock()
    manager._consolidation_llm = None
    register_skill_store_provider(MagicMock)

    with patch(f"{_MODULE}.get_memory_manager", return_value=manager):
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["failed_tool_calls"] == 1
    assert result["proposal"] is None


@pytest.mark.asyncio
async def test_without_a_skill_store_provider_no_proposal_is_drafted(tmp_path: Path) -> None:
    await _closed_turn_log(tmp_path, failed=True)
    manager = MagicMock()
    manager._consolidation_llm = MagicMock(spec=BaseChatModel)

    with patch(f"{_MODULE}.get_memory_manager", return_value=manager):
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["failed_tool_calls"] == 1
    assert result["proposal"] is None


@pytest.mark.asyncio
async def test_a_finished_turn_surfaces_a_proposal_through_the_idle_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whole chain on real parts: run end -> enqueue -> idle window -> event log read -> completion event."""
    from myrm_agent_harness.agent._internals import _agent_helpers
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

    await _closed_turn_log(tmp_path, failed=True)
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
        await asyncio.gather(*_agent_helpers._background_tasks)
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


@pytest.mark.asyncio
async def test_earlier_turns_of_the_chat_never_feed_the_current_proposal(tmp_path: Path) -> None:
    """The chat file accumulates every turn; a clean turn must not re-trigger an old turn's failures."""
    await _closed_turn_log(tmp_path, failed=True)
    await asyncio.sleep(0.01)  # the next turn starts strictly later than the previous one's events
    await _closed_turn_log(tmp_path, failed=False)

    with patch(f"{_MODULE}._capture_skill_proposal", new_callable=AsyncMock) as capture:
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["failed_tool_calls"] == 0
    capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_burst_of_quick_turns_is_covered_by_the_earliest_enqueued_since(tmp_path: Path) -> None:
    """The idle timer restarts each turn and the registry keeps the earliest task, so one run spans the burst."""
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=_CHAT_ID)
    turns: list[EventLogger] = []
    for _ in range(2):
        await asyncio.sleep(0.01)
        logger = _logger_for(backend)
        await logger.start()
        await _log_tool_call(logger, failed=True)
        await logger.close()
        turns.append(logger)
    set_event_logger(turns[-1])

    with patch(f"{_MODULE}._capture_skill_proposal", new_callable=AsyncMock, return_value=None):
        latest_only = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)
        whole_burst = await run_session_evidence_extraction(_task(since=turns[0].started_at), _RUNTIME_SESSION_ID)

    assert latest_only["failed_tool_calls"] == 1
    assert whole_burst["failed_tool_calls"] == 2


@pytest.mark.asyncio
async def test_a_backend_reused_across_turns_keeps_the_current_turn_visible(tmp_path: Path) -> None:
    """Pooled units reuse one backend; the second turn's events must be persisted, the first turn's excluded."""
    backend = FileEventLogBackend(log_dir=tmp_path, session_id=_CHAT_ID)
    first = _logger_for(backend)
    await first.start()
    await _log_tool_call(first, failed=True, error="old failure")
    await first.close()
    await asyncio.sleep(0.01)
    second = _logger_for(backend)
    await second.start()
    await _log_tool_call(second, failed=True, error="new failure")
    await second.close()
    set_event_logger(second)

    with patch(f"{_MODULE}._capture_skill_proposal", new_callable=AsyncMock, return_value=None) as capture:
        result = await run_session_evidence_extraction(_task(), _RUNTIME_SESSION_ID)

    assert result["failed_tool_calls"] == 1
    assert "new failure" in capture.await_args.args[3]
    assert "old failure" not in capture.await_args.args[3]


def _call(index: int, *, ok: bool = True, fault_side: str | None = None, error: str | None = None) -> ToolCallRecord:
    return ToolCallRecord(
        sequence=index,
        tool_name=f"tool_{index}",
        start_time=float(index),
        success=ok,
        error=error,
        fault_side=fault_side,
    )


def test_trajectory_keeps_each_failure_with_its_neighbours_and_collapses_clean_runs() -> None:
    calls = [_call(i) for i in range(1, 8)]
    calls[4] = _call(5, ok=False, fault_side="harness_tool", error="boom")

    trajectory = _format_trajectory(calls)

    assert trajectory.splitlines() == [
        "Tool calls in order:",
        "... 3 successful tool calls ...",
        "4. tool_4 -> ok",
        "5. tool_5 -> FAILED (harness_tool): boom",
        "6. tool_6 -> ok",
        "... 1 successful tool calls ...",
    ]


def test_trajectory_truncates_long_errors_and_names_unattributed_failures() -> None:
    trajectory = _format_trajectory([_call(1, ok=False, error="x" * 5000)])

    assert "FAILED (unattributed): " + "x" * 400 in trajectory
    assert "x" * 401 not in trajectory
