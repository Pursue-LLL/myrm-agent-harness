"""Tests for LocalFileOpsMixin destructive-action hook payloads.

Ensures write/append/delete hooks carry the current chat session id so the
server-side SnapshotInterceptor can create workspace snapshots for file
operations (not only bash). Without a bound chat context the session_id is
None and the hook stays inert.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.context_management.infra.session_lock import (
    reset_current_chat_id,
    set_current_chat_id,
)
from myrm_agent_harness.toolkits.code_execution.executors.local._file_ops import (
    LocalFileOpsMixin,
)


class _TestOps(LocalFileOpsMixin):
    """Concrete mixin host backed by a temp workspace."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._readonly_paths: list[str] = []
        self._current_workspace: Path | None = None

    async def resolve_path(self, path: str) -> str:
        return str(self._root / path)

    def _log_context_file_access(self, path: str, success: bool) -> None:
        pass

    @property
    def workspace_path(self) -> str:
        return str(self._root)


def _hook_patch():
    return patch(
        "myrm_agent_harness.toolkits.code_execution.executors.local._file_ops.trigger_destructive_action_hook",
        new_callable=AsyncMock,
    )


@pytest.mark.asyncio
async def test_write_file_hook_payload_includes_session_id(tmp_path: Path) -> None:
    token = set_current_chat_id("chat-abc")
    try:
        ops = _TestOps(tmp_path)
        with _hook_patch() as hook:
            await ops.write_file("a.txt", "hello")

        hook.assert_awaited_once()
        kwargs = hook.call_args.kwargs
        assert kwargs["action_type"] == "file_write"
        assert kwargs["payload"]["session_id"] == "chat-abc"
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"
    finally:
        reset_current_chat_id(token)


@pytest.mark.asyncio
async def test_append_file_hook_payload_includes_session_id(tmp_path: Path) -> None:
    token = set_current_chat_id("chat-xyz")
    try:
        ops = _TestOps(tmp_path)
        with _hook_patch() as hook:
            await ops.append_file("log.txt", "line\n")

        kwargs = hook.call_args.kwargs
        assert kwargs["action_type"] == "file_append"
        assert kwargs["payload"]["session_id"] == "chat-xyz"
    finally:
        reset_current_chat_id(token)


@pytest.mark.asyncio
async def test_delete_file_hook_payload_includes_session_id(tmp_path: Path) -> None:
    token = set_current_chat_id("chat-del")
    try:
        target = tmp_path / "gone.txt"
        target.write_text("x", encoding="utf-8")
        ops = _TestOps(tmp_path)
        with _hook_patch() as hook:
            await ops.delete_file("gone.txt")

        kwargs = hook.call_args.kwargs
        assert kwargs["action_type"] == "file_delete"
        assert kwargs["payload"]["session_id"] == "chat-del"
        assert not target.exists()
    finally:
        reset_current_chat_id(token)


@pytest.mark.asyncio
async def test_write_file_hook_payload_none_session_outside_agent(tmp_path: Path) -> None:
    """Outside an agent turn no chat id is bound and the hook stays inert."""
    ops = _TestOps(tmp_path)
    with _hook_patch() as hook:
        await ops.write_file("a.txt", "hello")

    kwargs = hook.call_args.kwargs
    assert kwargs["payload"].get("session_id") is None
