"""Pointer actions are refused while an injected overlay window covers the desktop.

Global-HID pointer events hit the topmost window. When that window is a protective
overlay (e.g. a privacy curtain) the click never reaches the target app, and the overlay
may read it as a passer-by's touch and relock the screen. The guard therefore fails
closed with a model-readable error. Targeted (pid) delivery, keyboard actions and
overlay-free sessions must stay untouched.

Pure-mock, headless-safe: the Quartz window query and the input primitives are stubbed.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.backends import macos as macos_mod
from myrm_agent_harness.toolkits.computer_use.backends import macos_input
from myrm_agent_harness.toolkits.computer_use.backends.cua_driver import CuaDriverBackend
from myrm_agent_harness.toolkits.computer_use.types import ActionResult

_CURTAIN = ["Privacy Curtain"]
_OVERLAY_WINDOW_ID = 77
_EVENT_PRIMITIVES = ("key_down", "key_up", "click", "move_to", "scroll", "hscroll", "drag")

_PointerCall = Callable[[macos_mod.MacOSBackend], Coroutine[object, object, ActionResult]]

# Modifiers are passed on purpose: a refusal must not leave a modifier key pressed.
_POINTER_ACTIONS: dict[str, _PointerCall] = {
    "click": lambda backend: backend.click(10, 20, modifiers=["shift"]),
    "mouse_move": lambda backend: backend.mouse_move(10, 20),
    "scroll": lambda backend: backend.scroll(10, 20, "down", modifiers=["shift"]),
    "drag": lambda backend: backend.drag(10, 20, 30, 40, modifiers=["shift"]),
}


@pytest.fixture()
def input_stub() -> Iterator[MagicMock]:
    """Replace the input primitives so no real event is ever posted."""
    stub = MagicMock(name="macos_input")
    stub.has_input_target.return_value = False
    with patch.object(macos_mod, "macos_input", stub):
        yield stub


@pytest.fixture()
def overlay_lookup() -> Iterator[MagicMock]:
    """Quartz overlay lookup; returns a window id (overlay on screen) by default."""
    lookup = MagicMock(return_value=_OVERLAY_WINDOW_ID)
    with patch.object(macos_mod, "_lowest_overlay_window_id", lookup):
        yield lookup


def _backend(titles: list[str] | None = None) -> macos_mod.MacOSBackend:
    backend = macos_mod.MacOSBackend()
    backend.set_excluded_capture_window_titles(_CURTAIN if titles is None else titles)
    return backend


@pytest.mark.parametrize("action", _POINTER_ACTIONS)
async def test_pointer_action_is_refused_while_overlay_is_on_screen(
    action: str, input_stub: MagicMock, overlay_lookup: MagicMock
) -> None:
    result = await _POINTER_ACTIONS[action](_backend())

    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("Safety:")
    assert "[REMEDY_HINT:" in result.error
    overlay_lookup.assert_called_once_with(frozenset(_CURTAIN))
    # Not even the modifier key-down: a refusal must never leave a key stuck.
    for primitive in _EVENT_PRIMITIVES:
        getattr(input_stub, primitive).assert_not_called()


@pytest.mark.parametrize("action", _POINTER_ACTIONS)
async def test_pointer_action_proceeds_when_no_overlay_is_on_screen(
    action: str, input_stub: MagicMock, overlay_lookup: MagicMock
) -> None:
    overlay_lookup.return_value = None

    result = await _POINTER_ACTIONS[action](_backend())

    assert result.success is True
    overlay_lookup.assert_called_once_with(frozenset(_CURTAIN))


async def test_overlay_is_never_queried_without_injected_titles(
    input_stub: MagicMock, overlay_lookup: MagicMock
) -> None:
    """Sessions without a curtain pay nothing: no window-list query at all."""
    backend = macos_mod.MacOSBackend()

    assert (await backend.click(10, 20)).success is True
    overlay_lookup.assert_not_called()
    input_stub.click.assert_called_once()


async def test_targeted_delivery_bypasses_the_guard(input_stub: MagicMock, overlay_lookup: MagicMock) -> None:
    """pid-targeted events skip HID hit-testing, so the overlay cannot intercept them."""
    input_stub.has_input_target.return_value = True

    result = await _backend().click(10, 20)

    assert result.success is True
    overlay_lookup.assert_not_called()
    input_stub.click.assert_called_once()


async def test_keyboard_actions_are_not_guarded(input_stub: MagicMock, overlay_lookup: MagicMock) -> None:
    """Keyboard events follow the focused app; the overlay never takes focus."""
    backend = _backend()

    assert (await backend.key("ctrl+c")).success is True
    assert (await backend.type_text("hello")).success is True
    overlay_lookup.assert_not_called()


async def test_cua_driver_fallback_cannot_click_through_the_overlay(
    input_stub: MagicMock, overlay_lookup: MagicMock
) -> None:
    """When cua-driver fails, the native fallback's HID click is refused like any other."""
    cua = CuaDriverBackend(fallback=_backend())
    cua._ensure_session = AsyncMock(side_effect=RuntimeError("cua-driver down"))  # type: ignore[method-assign]

    result = await cua.click(10, 20)

    assert result.success is False
    assert result.error is not None
    assert result.error.startswith("Safety:")
    input_stub.click.assert_not_called()


def test_has_input_target_follows_the_task_scoped_target() -> None:
    macos_input.clear_input_target()
    assert macos_input.has_input_target() is False

    macos_input.set_input_target(4242)
    try:
        assert macos_input.has_input_target() is True
    finally:
        macos_input.clear_input_target()
    assert macos_input.has_input_target() is False


def test_non_positive_pid_is_not_a_target() -> None:
    macos_input.set_input_target(-5)
    try:
        assert macos_input.has_input_target() is False
    finally:
        macos_input.clear_input_target()
