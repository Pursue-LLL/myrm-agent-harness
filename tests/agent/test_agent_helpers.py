from unittest.mock import MagicMock, patch

from myrm_agent_harness.agent._internals._agent_helpers import schedule_post_run_idle_tasks


@patch("myrm_agent_harness.agent._internals._agent_helpers._fire_and_forget")
@patch("myrm_agent_harness.agent.background_worker.registry.get_idle_task_registry")
@patch("myrm_agent_harness.agent.background_worker.idle_worker.schedule_idle_task")
def test_schedule_post_run_idle_tasks_token_window(mock_schedule, mock_get_registry, mock_fire):
    # Mock registry
    mock_registry = MagicMock()
    mock_get_registry.return_value = mock_registry

    # Create messages exceeding the 16000 character limit
    long_content = "A" * 10000
    messages = [
        {"role": "user", "content": long_content}, # 10000 chars
        {"role": "assistant", "content": long_content}, # 10000 chars
        {"role": "user", "content": "Short message"}, # 13 chars
    ]

    merged_context = {
        "session_id": "sess_1",
        "workspace_root": "/tmp/test",
        "chat_id": "chat_1",
        "messages": messages,
    }

    schedule_post_run_idle_tasks(merged_context)

    # Assert registry enqueue was called for cognitive_derivation
    derivation_calls = [
        call for call in mock_registry.enqueue.call_args_list
        if call[0][2] == "cognitive_derivation"
    ]

    assert len(derivation_calls) == 1
    call_args = derivation_calls[0][0]
    payload = call_args[3]

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
    mock_registry = MagicMock()
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

    schedule_post_run_idle_tasks(merged_context)

    # Assert registry enqueue was called for cognitive_derivation
    derivation_calls = [
        call for call in mock_registry.enqueue.call_args_list
        if call[0][2] == "cognitive_derivation"
    ]

    assert len(derivation_calls) == 1
    call_args = derivation_calls[0][0]
    payload = call_args[3]

    assert "messages" in payload
    serialized_msgs = payload["messages"]

    assert len(serialized_msgs) == 2
    assert serialized_msgs[0]["content"] == "Hello"
    assert serialized_msgs[1]["content"] == "Hi"
