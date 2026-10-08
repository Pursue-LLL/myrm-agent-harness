"""Windows pointer guard while privacy curtain titles are injected (mocked user32)."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.backends import windows as win_mod
from myrm_agent_harness.toolkits.computer_use.types import ActionResult

_CURTAIN = ["Privacy Curtain"]
_OVERLAY_HWND = 9001

_PointerCall = Callable[[win_mod.WindowsBackend], Coroutine[object, object, ActionResult]]

_POINTER_ACTIONS: dict[str, _PointerCall] = {
    "click": lambda backend: backend.click(10, 20),
    "mouse_move": lambda backend: backend.mouse_move(10, 20),
    "scroll": lambda backend: backend.scroll(10, 20, "down"),
    "drag": lambda backend: backend.drag(10, 20, 30, 40),
}


def _backend() -> win_mod.WindowsBackend:
    backend = win_mod.WindowsBackend()
    backend.set_excluded_capture_window_titles(_CURTAIN)
    return backend


@pytest.mark.parametrize("action", _POINTER_ACTIONS)
async def test_pointer_refused_when_overlay_hwnd_present(action: str) -> None:
    with patch.object(win_mod, "_lowest_overlay_hwnd", MagicMock(return_value=_OVERLAY_HWND)):
        result = await _POINTER_ACTIONS[action](_backend())

    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("Safety:")


@pytest.mark.parametrize("action", _POINTER_ACTIONS)
async def test_pointer_proceeds_when_no_overlay(action: str) -> None:
    with (
        patch.object(win_mod, "_lowest_overlay_hwnd", MagicMock(return_value=None)),
        patch.object(win_mod.asyncio, "to_thread", AsyncMock(return_value=None)),
    ):
        result = await _POINTER_ACTIONS[action](_backend())

    assert result.success is True
