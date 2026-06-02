"""PTC builtin ``session_store`` / ``session_load`` / ``session_keys`` tests.

Covers:
- Round-trip persistence under an IPC call context.
- Cross-call isolation between distinct session ids.
- Validation errors (empty key, missing value, oversize payload).
- Graceful failure when no IPC context is bound.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.mcp.builtin_session_store import (
    SessionStoreError,
    session_keys_handler,
    session_load_handler,
    session_store_handler,
)
from myrm_agent_harness.agent.skills.mcp.ipc_proxy import (
    IPCCallContext,
    _ipc_call_context,
)


def _ipc_ctx(session_id: str, workspace_root: Path) -> IPCCallContext:
    return IPCCallContext(
        session_id=session_id, workspace_root=str(workspace_root), trace_id="test"
    )


@pytest.mark.asyncio
async def test_session_store_round_trip(tmp_path: Path) -> None:
    token = _ipc_call_context.set(_ipc_ctx("chat-A", tmp_path))
    try:
        await session_store_handler({"key": "ids", "value": [1, 2, 3]})
        assert await session_load_handler({"key": "ids"}) == [1, 2, 3]
        assert await session_keys_handler({}) == ["ids"]
    finally:
        _ipc_call_context.reset(token)


@pytest.mark.asyncio
async def test_session_store_isolated_per_session(tmp_path: Path) -> None:
    token_a = _ipc_call_context.set(_ipc_ctx("chat-A", tmp_path))
    try:
        await session_store_handler({"key": "x", "value": "alpha"})
    finally:
        _ipc_call_context.reset(token_a)

    token_b = _ipc_call_context.set(_ipc_ctx("chat-B", tmp_path))
    try:
        assert await session_load_handler({"key": "x"}) is None
        await session_store_handler({"key": "x", "value": "beta"})
        assert await session_load_handler({"key": "x"}) == "beta"
    finally:
        _ipc_call_context.reset(token_b)

    token_a2 = _ipc_call_context.set(_ipc_ctx("chat-A", tmp_path))
    try:
        assert await session_load_handler({"key": "x"}) == "alpha"
    finally:
        _ipc_call_context.reset(token_a2)


@pytest.mark.asyncio
async def test_session_store_rejects_empty_key(tmp_path: Path) -> None:
    token = _ipc_call_context.set(_ipc_ctx("chat-X", tmp_path))
    try:
        with pytest.raises(SessionStoreError):
            await session_store_handler({"key": "", "value": 1})
    finally:
        _ipc_call_context.reset(token)


@pytest.mark.asyncio
async def test_session_store_requires_value_field(tmp_path: Path) -> None:
    token = _ipc_call_context.set(_ipc_ctx("chat-X", tmp_path))
    try:
        with pytest.raises(SessionStoreError):
            await session_store_handler({"key": "k"})
    finally:
        _ipc_call_context.reset(token)


@pytest.mark.asyncio
async def test_session_store_rejects_oversize_payload(tmp_path: Path) -> None:
    token = _ipc_call_context.set(_ipc_ctx("chat-X", tmp_path))
    huge = "x" * (300 * 1024)
    try:
        with pytest.raises(SessionStoreError):
            await session_store_handler({"key": "big", "value": huge})
    finally:
        _ipc_call_context.reset(token)


@pytest.mark.asyncio
async def test_session_store_requires_ipc_context() -> None:
    with pytest.raises(SessionStoreError):
        await session_store_handler({"key": "k", "value": 1})


@pytest.mark.asyncio
async def test_session_load_returns_none_when_missing(tmp_path: Path) -> None:
    token = _ipc_call_context.set(_ipc_ctx("chat-X", tmp_path))
    try:
        assert await session_load_handler({"key": "absent"}) is None
    finally:
        _ipc_call_context.reset(token)


@pytest.mark.parametrize(
    "malicious_sid",
    [
        "../../etc/passwd",
        "..",
        "../escape",
        "chat/with/slash",
        "chat\\back",
        "../",
        "",
        ".",
        " leading-space",
        "a" * 200,
    ],
)
@pytest.mark.asyncio
async def test_session_store_rejects_path_traversal(
    tmp_path: Path, malicious_sid: str
) -> None:
    """Path-traversal hardening: malformed session ids must not escape workspace.

    Mirrors the threat where a PTC script overwrites ``_SESSION_ID`` to point at
    files outside ``<workspace>/.session_store/``.
    """
    token = _ipc_call_context.set(_ipc_ctx(malicious_sid, tmp_path))
    try:
        with pytest.raises(SessionStoreError):
            await session_store_handler({"key": "k", "value": 1})
    finally:
        _ipc_call_context.reset(token)
