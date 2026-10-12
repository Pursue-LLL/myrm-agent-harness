import asyncio
from pathlib import Path
from unittest.mock import create_autospec, patch

from myrm_agent_harness.agent._internals._agent_helpers import schedule_post_run_idle_tasks
from myrm_agent_harness.agent.background_worker.registry import IdleTaskRegistry, get_idle_task_registry


def _new_registry() -> IdleTaskRegistry:
    """Autospec'd registry: a drifted ``enqueue`` call signature fails instead of being swallowed by a bare mock."""
    return create_autospec(IdleTaskRegistry, instance=True)


@patch("myrm_agent_harness.agent._internals._agent_helpers._fire_and_forget")
@patch("myrm_agent_harness.agent.background_worker.registry.get_idle_task_registry")
@patch("myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task")
def test_schedule_post_run_idle_tasks_token_window(mock_schedule, mock_get_registry, mock_fire):
    # Mock registry
    mock_registry = _new_registry()
    mock_get_registry.return_value = mock_registry

    # Create messages exceeding the 16000 character limit
    long_content = "A" * 10000
    messages = [
        {"role": "user", "content": long_content},  # 10000 chars
        {"role": "assistant", "content": long_content},  # 10000 chars
        {"role": "user", "content": "Short message"},  # 13 chars
    ]

    merged_context = {
        "session_id": "sess_1",
        "workspace_root": "/tmp/test",
        "chat_id": "chat_1",
        "messages": messages,
    }

    schedule_post_run_idle_tasks(merged_context, derive_memories=True)

    # Assert registry enqueue was called for cognitive_derivation
    derivation_calls = [call for call in mock_registry.enqueue.call_args_list if call[0][1] == "cognitive_derivation"]

    assert len(derivation_calls) == 1
    call_args = derivation_calls[0][0]
    payload = call_args[2]

    assert "messages" in payload
    serialized_msgs = payload["messages"]

    # Verify Token-Aware Sliding Window logic
    # Total chars allowed: 16000
    # Messages processed in reverse:
    # 1. "Short message" (13 chars) -> included
    # 2. assistant msg (10000 chars) -> included (total 10013)
    # 3. user msg (10000 chars) -> truncated to 16000 - 10013 = 5987 chars + "...[TRUNCATED]"

    assert len(serialized_msgs) == 3
    assert serialized_msgs[-1]["content"] == "Short message"
    assert len(serialized_msgs[-2]["content"]) == 10000

    # The oldest message should be truncated
    first_msg_content = serialized_msgs[0]["content"]
    assert first_msg_content.endswith("...[TRUNCATED]")
    # It should be 5987 + len("...[TRUNCATED]") = 5987 + 14 = 6001 chars roughly
    assert len(first_msg_content) > 1000
    assert len(first_msg_content) < 10000


@patch("myrm_agent_harness.agent._internals._agent_helpers._fire_and_forget")
@patch("myrm_agent_harness.agent.background_worker.registry.get_idle_task_registry")
@patch("myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task")
def test_schedule_post_run_idle_tasks_no_truncation(mock_schedule, mock_get_registry, mock_fire):
    # Mock registry
    mock_registry = _new_registry()
    mock_get_registry.return_value = mock_registry

    # Create small messages
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]

    merged_context = {
        "session_id": "sess_1",
        "workspace_root": "/tmp/test",
        "chat_id": "chat_1",
        "messages": messages,
    }

    schedule_post_run_idle_tasks(merged_context, derive_memories=True)

    # Assert registry enqueue was called for cognitive_derivation
    derivation_calls = [call for call in mock_registry.enqueue.call_args_list if call[0][1] == "cognitive_derivation"]

    assert len(derivation_calls) == 1
    call_args = derivation_calls[0][0]
    payload = call_args[2]

    assert "messages" in payload
    serialized_msgs = payload["messages"]

    assert len(serialized_msgs) == 2
    assert serialized_msgs[0]["content"] == "Hello"
    assert serialized_msgs[1]["content"] == "Hi"


@patch("myrm_agent_harness.agent._internals._agent_helpers._fire_and_forget")
@patch("myrm_agent_harness.agent.background_worker.registry.get_idle_task_registry")
def test_schedule_post_run_idle_tasks_serializes_message_objects(mock_get_registry, mock_fire):
    """BaseMessage inputs must serialize to the same role/content shape as dicts."""
    from langchain_core.messages import AIMessage, HumanMessage

    mock_get_registry.return_value = _new_registry()
    messages = [HumanMessage(content="ping"), AIMessage(content="pong")]

    schedule_post_run_idle_tasks(
        {
            "session_id": "sess_2",
            "workspace_root": "/tmp/test",
            "chat_id": "chat_2",
            "messages": messages,
        },
        derive_memories=True,
    )

    derivation_calls = [
        call for call in mock_get_registry.return_value.enqueue.call_args_list if call[0][1] == "cognitive_derivation"
    ]
    assert len(derivation_calls) == 1
    serialized = derivation_calls[0][0][2]["messages"]
    assert [m["content"] for m in serialized] == ["ping", "pong"]


_IMAGE_BLOCK = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "iVBORw0KGgo" * 3000}}


def _derivation_messages(messages: list[object]) -> list[dict[str, str]]:
    with (
        patch("myrm_agent_harness.agent._internals._agent_helpers._fire_and_forget"),
        patch("myrm_agent_harness.agent.background_worker.registry.get_idle_task_registry") as mock_get_registry,
    ):
        mock_get_registry.return_value = _new_registry()
        schedule_post_run_idle_tasks(
            {"session_id": "sess_3", "workspace_root": "/tmp/test", "chat_id": "chat_3", "messages": messages},
            derive_memories=True,
        )
        calls = [
            call
            for call in mock_get_registry.return_value.enqueue.call_args_list
            if call[0][1] == "cognitive_derivation"
        ]
    assert len(calls) == 1
    return calls[0][0][2]["messages"]


def test_schedule_post_run_idle_tasks_drops_image_blocks_and_keeps_history():
    """An image turn must not flood the derivation window with base64 or evict earlier history."""
    from langchain_core.messages import AIMessage, HumanMessage

    serialized = _derivation_messages(
        [
            HumanMessage(content="I prefer short answers"),
            AIMessage(content="Noted"),
            HumanMessage(content=[{"type": "text", "text": "fix this error"}, _IMAGE_BLOCK]),
            AIMessage(content="Fixed"),
        ]
    )

    assert [m["content"] for m in serialized] == ["I prefer short answers", "Noted", "fix this error", "Fixed"]
    assert all("base64" not in m["content"] for m in serialized)


def test_schedule_post_run_idle_tasks_skips_image_only_messages_and_cleans_dict_content():
    from langchain_core.messages import AIMessage, HumanMessage

    serialized = _derivation_messages(
        [
            {"role": "user", "content": [{"type": "text", "text": "see attached"}, _IMAGE_BLOCK]},
            HumanMessage(content=[_IMAGE_BLOCK]),
            AIMessage(content="done"),
        ]
    )

    assert [m["content"] for m in serialized] == ["see attached", "done"]


def test_schedule_post_run_idle_tasks_persists_runnable_tasks_in_real_registry(tmp_path: Path, monkeypatch):
    """End-to-end against the real SQLite registry: tasks are enqueued and can be acquired by session id."""
    from myrm_agent_harness.agent.background_worker import registry as registry_module

    monkeypatch.setattr(registry_module, "_registry_instance", None)

    async def scenario() -> list[str]:
        with patch("myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task"):
            schedule_post_run_idle_tasks(
                {
                    "session_id": "sess_real",
                    "workspace_root": str(tmp_path),
                    "chat_id": "chat_real",
                    "messages": [{"role": "user", "content": "I prefer short answers"}],
                },
                derive_memories=True,
            )
            await asyncio.sleep(0.3)
        registry = get_idle_task_registry(str(tmp_path))
        acquired: list[str] = []
        while (record := await registry.acquire_next("sess_real")) is not None:
            acquired.append(record.task_type)
        return acquired

    acquired = asyncio.run(scenario())

    assert {"cognitive_consolidation", "cognitive_derivation", "context_compaction"} <= set(acquired)


@patch("myrm_agent_harness.agent._internals._agent_helpers._fire_and_forget")
@patch("myrm_agent_harness.agent.background_worker.registry.get_idle_task_registry")
@patch("myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task")
def test_schedule_post_run_idle_tasks_skips_derivation_when_not_allowed(mock_schedule, mock_get_registry, mock_fire):
    """Derivation writes memories from the chat, so it is not enqueued when extraction is disallowed."""
    mock_registry = _new_registry()
    mock_get_registry.return_value = mock_registry

    schedule_post_run_idle_tasks(
        {
            "session_id": "sess_4",
            "workspace_root": "/tmp/test",
            "chat_id": "chat_4",
            "messages": [{"role": "user", "content": "I do not eat spicy food"}],
        },
        derive_memories=False,
    )

    enqueued = {call[0][1] for call in mock_registry.enqueue.call_args_list}
    assert "cognitive_derivation" not in enqueued
    assert {"cognitive_consolidation", "context_compaction"} <= enqueued
    mock_schedule.assert_called_once()


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
