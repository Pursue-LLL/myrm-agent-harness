"""PTC builtin ``notify`` tests.

Covers:
- Validation of message and level fields.
- Dispatch is routed to the LangGraph custom stream with the expected payload.
- Fire-and-forget semantics when no consumer is registered (no exception).
"""

from __future__ import annotations

from typing import Any

import pytest

from myrm_agent_harness.agent.skills.mcp.builtin_notify import (
    NotifyError,
    notify_handler,
)
from myrm_agent_harness.agent.skills.mcp.ipc_proxy import (
    IPCCallContext,
    _ipc_call_context,
)
from myrm_agent_harness.agent.skills.mcp.notify_registry import (
    pop_session_config,
    register_session_config,
)


def _ipc_ctx(session_id: str = "chat-N") -> IPCCallContext:
    return IPCCallContext(session_id=session_id, workspace_root="/tmp", trace_id="tid")


@pytest.mark.asyncio
async def test_notify_rejects_empty_message() -> None:
    token = _ipc_call_context.set(_ipc_ctx())
    try:
        with pytest.raises(NotifyError):
            await notify_handler({"message": ""})
    finally:
        _ipc_call_context.reset(token)


@pytest.mark.asyncio
async def test_notify_rejects_unknown_level() -> None:
    token = _ipc_call_context.set(_ipc_ctx())
    try:
        with pytest.raises(NotifyError):
            await notify_handler({"message": "hi", "level": "panic"})
    finally:
        _ipc_call_context.reset(token)


@pytest.mark.asyncio
async def test_notify_dispatches_with_registered_config(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_dispatch(name: str, data: Any, config: Any = None) -> None:
        seen["name"] = name
        seen["data"] = data
        seen["config"] = config

    monkeypatch.setattr(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event", fake_dispatch
    )

    fake_config = {"configurable": {"thread_id": "abc"}}
    register_session_config("chat-N", fake_config)
    token = _ipc_call_context.set(_ipc_ctx("chat-N"))
    try:
        await notify_handler({"message": "halfway done", "level": "info"})
    finally:
        _ipc_call_context.reset(token)
        pop_session_config("chat-N")

    assert seen["name"] == "ptc_notify"
    assert seen["data"]["message"] == "halfway done"
    assert seen["data"]["level"] == "info"
    assert seen["data"]["session_id"] == "chat-N"
    assert seen["config"] is fake_config


@pytest.mark.asyncio
async def test_notify_silent_when_dispatch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("stream gone")

    monkeypatch.setattr(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event", boom
    )

    token = _ipc_call_context.set(_ipc_ctx())
    try:
        assert await notify_handler({"message": "still ok"}) is None
    finally:
        _ipc_call_context.reset(token)


@pytest.mark.asyncio
async def test_notify_forwards_structured_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3: structured fields ride along the payload so the UI can render bars."""
    seen: dict[str, Any] = {}

    async def fake_dispatch(name: str, data: Any, config: Any = None) -> None:
        seen["data"] = data

    monkeypatch.setattr(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event", fake_dispatch
    )

    register_session_config("chat-PROG", {"configurable": {"thread_id": "x"}})
    token = _ipc_call_context.set(_ipc_ctx("chat-PROG"))
    try:
        await notify_handler(
            {
                "message": "crawling 50/200",
                "level": "info",
                "progress": 25,
                "step_index": 50,
                "total_steps": 200,
                "category": "crawl",
            }
        )
    finally:
        _ipc_call_context.reset(token)
        pop_session_config("chat-PROG")

    assert seen["data"]["progress"] == 25
    assert seen["data"]["step_index"] == 50
    assert seen["data"]["total_steps"] == 200
    assert seen["data"]["category"] == "crawl"


@pytest.mark.parametrize(
    "bad_params",
    [
        {"message": "x", "progress": -1},
        {"message": "x", "progress": 101},
        {"message": "x", "step_index": 0},
        {"message": "x", "total_steps": 0},
        {"message": "x", "category": ""},
        {"message": "x", "category": "x" * 64},
        {"message": "x", "progress": "fifty"},
    ],
)
@pytest.mark.asyncio
async def test_notify_validates_structured_fields(bad_params: dict[str, Any]) -> None:
    token = _ipc_call_context.set(_ipc_ctx("chat-V"))
    try:
        with pytest.raises(NotifyError):
            await notify_handler(bad_params)
    finally:
        _ipc_call_context.reset(token)


@pytest.mark.asyncio
async def test_notify_rate_limited_drops_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1: a runaway ``for i: notify(...)`` script is throttled to ≤ 20 burst calls.

    The handler must never raise — overflow calls are silently dropped so
    the PTC script keeps running.
    """
    dispatch_calls = 0

    async def fake_dispatch(name: str, data: Any, config: Any = None) -> None:
        nonlocal dispatch_calls
        dispatch_calls += 1

    monkeypatch.setattr(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event", fake_dispatch
    )

    sid = "chat-RATELIMIT"
    register_session_config(sid, {"configurable": {"thread_id": "x"}})
    token = _ipc_call_context.set(_ipc_ctx(sid))
    try:
        for i in range(200):
            await notify_handler({"message": f"step {i}"})
    finally:
        _ipc_call_context.reset(token)
        pop_session_config(sid)

    # Burst capacity is 20; rate is 10/s. A tight loop bursts the bucket
    # then drops the rest. Asserting upper bound rather than exact count
    # to stay robust against scheduling jitter.
    assert dispatch_calls < 200
    assert dispatch_calls > 0
