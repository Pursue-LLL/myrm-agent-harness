"""Tests for llm_observability prompt preview builder and passive event recording."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.event_log.llm_observability import (
    build_prompt_preview,
    record_llm_request,
)


class TestBuildPromptPreview:
    def test_truncates_long_content(self) -> None:
        long = "x" * 600
        preview = build_prompt_preview([{"role": "user", "content": long}], max_len=500)
        assert len(preview) <= 530
        assert "truncated" in preview

    def test_includes_roles(self) -> None:
        preview = build_prompt_preview(
            [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hi"},
            ]
        )
        assert "[system]" in preview
        assert "[user]" in preview

    def test_tool_calls_placeholder(self) -> None:
        preview = build_prompt_preview(
            [{"role": "assistant", "tool_calls": [{"id": "call-1"}]}]
        )
        assert "[assistant] <tool_calls>" in preview

    def test_empty_messages_returns_empty_string(self) -> None:
        assert build_prompt_preview([]) == ""
        assert build_prompt_preview([{"role": "user", "content": "   "}]) == ""


class TestRecordLlmRequest:
    @pytest.mark.asyncio
    async def test_no_event_logger_returns_early(self) -> None:
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_event_logger",
            return_value=None,
        ):
            await record_llm_request("gpt-4o", [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_logs_llm_request_event(self) -> None:
        mock_logger = AsyncMock()
        messages = [{"role": "user", "content": "hello"}]
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_event_logger",
            return_value=mock_logger,
        ):
            await record_llm_request("gpt-4o", messages)

        mock_logger.log.assert_awaited_once()
        event_type, payload = mock_logger.log.await_args.args
        assert event_type == "llm_request"
        assert payload["model_name"] == "gpt-4o"
        assert payload["message_count"] == 1
        assert "[user] hello" in payload["prompt_preview"]

    @pytest.mark.asyncio
    async def test_swallows_logger_errors(self) -> None:
        mock_logger = AsyncMock()
        mock_logger.log.side_effect = RuntimeError("event log unavailable")
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_event_logger",
            return_value=mock_logger,
        ):
            await record_llm_request("gpt-4o", [])
