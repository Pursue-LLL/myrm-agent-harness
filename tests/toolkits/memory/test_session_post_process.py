"""Tests for memory domain session post-process runner."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.session_post_process import run_session_post_process


@pytest.mark.asyncio
async def test_run_session_post_process_empty_tasks() -> None:
    await run_session_post_process([], [{"role": "user", "content": "hi"}], "chat-1")


@pytest.mark.asyncio
async def test_run_session_post_process_logs_task_failures() -> None:
    async def _fail(_messages: list[dict[str, str]], _chat_id: str | None) -> None:
        raise RuntimeError("task failed")

    async def _ok(_messages: list[dict[str, str]], _chat_id: str | None) -> None:
        return None

    await run_session_post_process([_fail, _ok], [{"role": "user", "content": "hi"}], "chat-2")
