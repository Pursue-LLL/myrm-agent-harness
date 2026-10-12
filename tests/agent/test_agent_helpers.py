import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, create_autospec, patch

import pytest
from langgraph.types import Command

from myrm_agent_harness.agent._internals import _agent_helpers
from myrm_agent_harness.agent._internals._agent_helpers import (
    extract_query_text,
    pop_checkpoint_incompatible_merged_context,
    reset_all_guards,
    schedule_post_run_idle_tasks,
)
from myrm_agent_harness.agent.background_worker import registry as registry_module
from myrm_agent_harness.agent.background_worker.registry import IdleTaskRegistry, get_idle_task_registry

_CONTEXT = {"session_id": "chat_real", "workspace_root": "/tmp/test", "chat_id": "real", "agent_id": "agent-1"}


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


def test_run_with_chat_id_enqueues_consolidation_and_compaction():
    registry, schedule = _schedule_with_mock_registry(_CONTEXT)

    assert _enqueued_types(registry) == {"cognitive_consolidation", "context_compaction"}
    schedule.assert_called_once()


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

    async def scenario() -> list[str]:
        with patch("myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task"):
            schedule_post_run_idle_tasks({**_CONTEXT, "workspace_root": str(tmp_path)})
            await asyncio.gather(*_agent_helpers._background_tasks)
        registry = get_idle_task_registry(str(tmp_path))
        acquired: list[str] = []
        while (record := await registry.acquire_next("chat_real")) is not None:
            acquired.append(record.task_type)
        return acquired

    acquired = asyncio.run(scenario())

    assert set(acquired) == {"cognitive_consolidation", "context_compaction"}


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


def test_schedule_failure_is_logged_and_never_raised():
    registry = create_autospec(IdleTaskRegistry, instance=True)
    with (
        patch("myrm_agent_harness.agent._internals._agent_helpers._fire_and_forget"),
        patch("myrm_agent_harness.agent.background_worker.registry.get_idle_task_registry", return_value=registry),
        patch(
            "myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task",
            side_effect=RuntimeError("no running loop"),
        ),
        patch.object(_agent_helpers, "logger") as logger,
    ):
        schedule_post_run_idle_tasks(_CONTEXT)

    logger.error.assert_called_once()


def test_init_usage_ledger_swallows_construction_failure(tmp_path):
    with (
        patch(
            "myrm_agent_harness.utils.token_economics.usage_ledger.UsageLedger",
            side_effect=OSError("read-only volume"),
        ),
        patch.object(_agent_helpers, "set_usage_ledger") as set_ledger,
    ):
        _agent_helpers.init_usage_ledger({"workspace_path": str(tmp_path)})

    set_ledger.assert_not_called()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("hello", "hello"),
        ([{"type": "image_url", "image_url": "x"}, {"type": "text", "text": "describe it"}], "describe it"),
        ([{"type": "image_url", "image_url": "x"}], ""),
        (Command(resume="approved"), "Resume: approved"),
        (42, "42"),
    ],
)
def test_extract_query_text(query: object, expected: str):
    assert extract_query_text(query) == expected


def test_pop_checkpoint_incompatible_merged_context_moves_only_callbacks():
    merged: dict[str, object] = {"goal_provider": object(), "on_loop_restart": object(), "chat_id": "c1"}
    callbacks = {key: merged[key] for key in ("goal_provider", "on_loop_restart")}

    stripped = pop_checkpoint_incompatible_merged_context(merged)

    assert stripped == callbacks
    assert merged == {"chat_id": "c1"}


def test_reset_all_guards_forwards_resume_and_budget_arguments():
    with (
        patch(
            "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.reset_loop_guard"
        ) as loop_guard,
        patch("myrm_agent_harness.agent.security.guards.context_budget.reset_context_budget_guard") as budget_guard,
    ):
        reset_all_guards(is_resume=True, graph_recursion_limit=50, unattended_mode=True)

    loop_guard.assert_called_once_with(is_resume=True, graph_recursion_limit=50, unattended_mode=True)
    budget_guard.assert_called_once_with(is_resume=True)
