"""Unit tests for send_user_message_async meta-tool."""

import json
from unittest.mock import patch

from myrm_agent_harness.agent.meta_tools.communication.send_user_message_async_tool import (
    MAX_ASYNC_MESSAGES_PER_TURN,
    create_send_user_message_async_tool,
    reset_turn_async_message_limit,
)


def test_send_user_message_async_progress_success() -> None:
    reset_turn_async_message_limit()
    tool = create_send_user_message_async_tool()

    with patch("myrm_agent_harness.agent.meta_tools.communication.send_user_message_async_tool.dispatch_custom_event") as mock_dispatch:
        res_str = tool.invoke({"message": "Refactoring module A...", "category": "progress"})
        res = json.loads(res_str)

        assert res["accepted"] is True
        assert res["category"] == "progress"
        assert res["call_id"].startswith("async_msg_")

        mock_dispatch.assert_called_once()
        args, _ = mock_dispatch.call_args
        assert args[0] == "async_user_message"
        assert args[1]["message"] == "Refactoring module A..."
        assert args[1]["category"] == "progress"
        assert args[1]["recommendation"] is None


def test_send_user_message_async_question_with_recommendation() -> None:
    reset_turn_async_message_limit()
    tool = create_send_user_message_async_tool()

    with patch("myrm_agent_harness.agent.meta_tools.communication.send_user_message_async_tool.dispatch_custom_event") as mock_dispatch:
        res_str = tool.invoke({
            "message": "Should we keep legacy routes?",
            "category": "question",
            "recommendation": "Keep legacy routes with deprecation notice",
        })
        res = json.loads(res_str)

        assert res["accepted"] is True
        assert res["category"] == "question"

        mock_dispatch.assert_called_once()
        args, _ = mock_dispatch.call_args
        assert args[1]["category"] == "question"
        assert args[1]["recommendation"] == "Keep legacy routes with deprecation notice"


def test_send_user_message_async_rate_limit_per_turn() -> None:
    reset_turn_async_message_limit()
    tool = create_send_user_message_async_tool()

    with patch("myrm_agent_harness.agent.meta_tools.communication.send_user_message_async_tool.dispatch_custom_event"):
        # First MAX calls should succeed
        for i in range(MAX_ASYNC_MESSAGES_PER_TURN):
            res = json.loads(tool.invoke({"message": f"Message {i}"}))
            assert res["accepted"] is True

        # Next call should be rate limited
        blocked_res = json.loads(tool.invoke({"message": "One more message"}))
        assert blocked_res["accepted"] is False
        assert "Rate limit reached" in blocked_res["error"]

        # Reset turn should clear limit
        reset_turn_async_message_limit()
        new_res = json.loads(tool.invoke({"message": "Fresh turn message"}))
        assert new_res["accepted"] is True


def test_send_user_message_async_empty_message_validation() -> None:
    reset_turn_async_message_limit()
    tool = create_send_user_message_async_tool()

    res = json.loads(tool.invoke({"message": "   "}))
    assert res["accepted"] is False
    assert "Message must not be empty" in res["error"]


def test_send_user_message_async_with_suggested_replies() -> None:
    reset_turn_async_message_limit()
    tool = create_send_user_message_async_tool()

    with patch("myrm_agent_harness.agent.meta_tools.communication.send_user_message_async_tool.dispatch_custom_event") as mock_dispatch:
        res_str = tool.invoke({
            "message": "Which approach do you prefer?",
            "category": "question",
            "recommendation": "Use approach A",
            "suggested_replies": ["Approach A", "Approach B", "Skip for now"],
        })
        res = json.loads(res_str)

        assert res["accepted"] is True
        assert res["category"] == "question"
        assert res["suggested_replies"] == ["Approach A", "Approach B", "Skip for now"]

        mock_dispatch.assert_called_once()
        args, _ = mock_dispatch.call_args
        assert args[0] == "async_user_message"
        assert args[1]["suggested_replies"] == ["Approach A", "Approach B", "Skip for now"]

