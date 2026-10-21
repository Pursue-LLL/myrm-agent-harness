"""Tests for the bash hook that reports commands to the execution interceptor."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from myrm_agent_harness.toolkits.code_execution.interceptor import (
    set_execution_interceptor,
    trigger_bash_action_hook,
)


class _RecordingInterceptor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def before_destructive_action(self, workspace_path: str, action_type: str, payload: dict) -> None:
        self.calls.append((workspace_path, action_type, payload))


@pytest.fixture
def interceptor() -> Iterator[_RecordingInterceptor]:
    recorder = _RecordingInterceptor()
    set_execution_interceptor(recorder)
    yield recorder
    set_execution_interceptor(None)


@pytest.mark.asyncio
async def test_file_mutating_command_is_reported_as_destructive(interceptor: _RecordingInterceptor) -> None:
    await trigger_bash_action_hook("/ws", "rm -rf build", "chat-1")

    assert interceptor.calls == [
        (
            "/ws",
            "bash",
            {"command": "rm -rf build", "session_id": "chat-1", "destructive": True, "external_effects": []},
        )
    ]


@pytest.mark.asyncio
async def test_external_effect_command_is_reported_without_destructive_flag(interceptor: _RecordingInterceptor) -> None:
    await trigger_bash_action_hook("/ws", "docker run -d postgres", "chat-1")

    assert len(interceptor.calls) == 1
    payload = interceptor.calls[0][2]
    assert payload["destructive"] is False
    assert payload["external_effects"] == ["container_cloud"]


@pytest.mark.asyncio
async def test_command_with_both_kinds_carries_both(interceptor: _RecordingInterceptor) -> None:
    await trigger_bash_action_hook("/ws", "rm -rf dist && git push origin main", "chat-1")

    payload = interceptor.calls[0][2]
    assert payload["destructive"] is True
    assert payload["external_effects"] == ["publish"]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["ls -la", "git status", "grep -r docker ."])
async def test_harmless_command_is_not_reported(interceptor: _RecordingInterceptor, command: str) -> None:
    await trigger_bash_action_hook("/ws", command, "chat-1")

    assert interceptor.calls == []


@pytest.mark.asyncio
async def test_without_interceptor_nothing_happens() -> None:
    set_execution_interceptor(None)

    await trigger_bash_action_hook("/ws", "rm -rf build", None)
