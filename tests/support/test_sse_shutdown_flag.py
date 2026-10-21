"""Unit tests for ``tests.support.sse_shutdown_flag``.

[INPUT]
- sse_starlette.sse::AppStatus (POS: process-global uvicorn shutdown signal shared by every EventSourceResponse)
- tests.support.sse_shutdown_flag::reset_sse_shutdown_flag (POS: pytest-only teardown helper clearing sse-starlette's process-global shutdown flag)

[OUTPUT]
- test_reset_clears_should_exit: flag is cleared after the watcher broadcast window
- test_missing_app_status_is_noop: safe no-op when the library drops the flag class

[POS]
Cover the reset helper without touching a real uvicorn server: the behaviour is
purely "clear the flag, ignore its absence", so swapping the real ``AppStatus``
reference is enough.
"""

from __future__ import annotations

import types

import pytest

from tests.support.sse_shutdown_flag import reset_sse_shutdown_flag


@pytest.mark.asyncio
async def test_reset_clears_should_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    app_status = types.SimpleNamespace(should_exit=True)
    monkeypatch.setattr("sse_starlette.sse.AppStatus", app_status)

    await reset_sse_shutdown_flag()

    assert app_status.should_exit is False


@pytest.mark.asyncio
async def test_missing_app_status_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr("sse_starlette.sse.AppStatus")

    await reset_sse_shutdown_flag()
