"""Tests for macos_input — macOS native input primitives (Quartz CGEvent).

Covers:
- Keycode mapping and shift-character handling
- Keyboard primitives: key_down/key_up/press/hotkey/write
- Mouse primitives: click/move_to/scroll/hscroll/drag
- State reads: size/position
- Event construction and posting via mocked Quartz
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.backends import macos_input
from myrm_agent_harness.toolkits.computer_use.backends.macos_input import _Point, _Size


def _fake_quartz() -> MagicMock:
    """Create a fully mocked Quartz module with named constants/functions."""
    q = MagicMock()
    q.CGEventCreateKeyboardEvent.return_value = MagicMock()
    q.CGEventCreateMouseEvent.return_value = MagicMock()
    q.CGEventCreateScrollWheelEvent.return_value = MagicMock()
    q.CGEventPost.return_value = None
    q.CGEventKeyboardSetUnicodeString.return_value = None
    q.CGEventCreate.return_value = MagicMock()
    q.CGEventGetLocation.return_value = MagicMock(x=100, y=200)
    q.CGMainDisplayID.return_value = 0
    q.CGDisplayPixelsWide.return_value = 1920
    q.CGDisplayPixelsHigh.return_value = 1080
    for name in (
        "kCGHIDEventTap",
        "kCGEventMouseMoved",
        "kCGEventLeftMouseDown",
        "kCGEventLeftMouseUp",
        "kCGEventLeftMouseDragged",
        "kCGEventRightMouseDown",
        "kCGEventRightMouseUp",
        "kCGEventOtherMouseDown",
        "kCGEventOtherMouseUp",
        "kCGMouseButtonLeft",
        "kCGMouseButtonRight",
        "kCGMouseButtonCenter",
        "kCGScrollEventUnitLine",
    ):
        setattr(q, name, MagicMock())
    return q


@pytest.fixture(autouse=True)
def _patch_quartz():
    """Inject fake Quartz module for all tests in this file."""
    fake = _fake_quartz()
    with patch.dict("sys.modules", {"Quartz": fake}):
        yield fake


class TestKeyCodes:
    def test_lowercase_letters_mapped(self) -> None:
        assert macos_input._KEYCODES["a"] == 0x00
        assert macos_input._KEYCODES["z"] == 0x06

    def test_uppercase_letters_share_lowercase_keycode(self) -> None:
        assert macos_input._KEYCODES["A"] == macos_input._KEYCODES["a"]
        assert macos_input._KEYCODES["Z"] == macos_input._KEYCODES["z"]

    def test_modifier_keys(self) -> None:
        assert macos_input._KEYCODES["command"] == 0x37
        assert macos_input._KEYCODES["shift"] == 0x38
        assert macos_input._KEYCODES["option"] == 0x3A
        assert macos_input._KEYCODES["ctrl"] == 0x3B

    def test_shift_characters_share_base_keycode(self) -> None:
        assert macos_input._KEYCODES["!"] == macos_input._KEYCODES["1"]
        assert macos_input._KEYCODES["@"] == macos_input._KEYCODES["2"]
        assert macos_input._KEYCODES["#"] == macos_input._KEYCODES["3"]

    def test_special_keys(self) -> None:
        assert macos_input._KEYCODES["enter"] == 0x24
        assert macos_input._KEYCODES["tab"] == 0x30
        assert macos_input._KEYCODES["esc"] == 0x35
        assert macos_input._KEYCODES["left"] == 0x7B
        assert macos_input._KEYCODES["up"] == 0x7E

    def test_is_shift_character(self) -> None:
        assert macos_input._is_shift_character("A") is True
        assert macos_input._is_shift_character("!") is True
        assert macos_input._is_shift_character("a") is False
        assert macos_input._is_shift_character("1") is False
        assert macos_input._is_shift_character("command") is False


class TestKeyboardPrimitives:
    @patch("time.sleep")
    def test_key_down_posts_keycode(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.key_down("a")
        _patch_quartz.CGEventCreateKeyboardEvent.assert_called_once_with(None, 0x00, True)
        _patch_quartz.CGEventPost.assert_called_once()

    @patch("time.sleep")
    def test_key_down_shift_character_adds_shift(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.key_down("A")
        calls = _patch_quartz.CGEventCreateKeyboardEvent.call_args_list
        assert calls[0].args[1] == macos_input._KEYCODES["shift"]
        assert calls[0].args[2] is True
        assert calls[1].args[1] == macos_input._KEYCODES["a"]
        assert calls[1].args[2] is True

    @patch("time.sleep")
    def test_key_up_posts_release(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.key_up("b")
        _patch_quartz.CGEventCreateKeyboardEvent.assert_called_once_with(None, 0x0B, False)
    @patch("time.sleep")
    def test_key_up_shift_character_releases_shift(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.key_up("!")
        calls = _patch_quartz.CGEventCreateKeyboardEvent.call_args_list
        assert calls[0].args[1] == macos_input._KEYCODES["1"]
        assert calls[0].args[2] is False
        assert calls[1].args[1] == macos_input._KEYCODES["shift"]
        assert calls[1].args[2] is False

    @patch("time.sleep")
    def test_press_down_then_up(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.press("enter")
        calls = _patch_quartz.CGEventCreateKeyboardEvent.call_args_list
        assert calls[0].args[1] == 0x24
        assert calls[0].args[2] is True
        assert calls[1].args[1] == 0x24
        assert calls[1].args[2] is False

    @patch("time.sleep")
    def test_hotkey_order_and_reverse_release(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.hotkey("command", "c")
        calls = _patch_quartz.CGEventCreateKeyboardEvent.call_args_list
        assert [c.args[1] for c in calls] == [
            macos_input._KEYCODES["command"],
            macos_input._KEYCODES["c"],
            macos_input._KEYCODES["c"],
            macos_input._KEYCODES["command"],
        ]
        assert [c.args[2] for c in calls] == [True, True, False, False]

    @patch("time.sleep")
    def test_write_uses_unicode_string(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.write("hi")
        assert _patch_quartz.CGEventKeyboardSetUnicodeString.call_count == 2
        assert _patch_quartz.CGEventPost.call_count == 4
        # Each char posts down+up
        macos_input.write("ab")
        assert _patch_quartz.CGEventKeyboardSetUnicodeString.call_count == 4

    @patch("time.sleep")
    def test_write_with_interval_sleeps(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.write("abc", interval=0.01)
        # 3 chars → 3 sleeps (plus key primitives don't sleep here)
        assert _mock_sleep.call_count >= 3


class TestMousePrimitives:
    @patch("time.sleep")
    def test_click_left(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.click(10, 20)
        events = _patch_quartz.CGEventCreateMouseEvent.call_args_list
        assert events[0].args[1] == _patch_quartz.kCGEventLeftMouseDown
        assert events[0].args[2] == (10, 20)
        assert events[1].args[1] == _patch_quartz.kCGEventLeftMouseUp

    @patch("time.sleep")
    def test_click_right(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.click(10, 20, button="right")
        events = _patch_quartz.CGEventCreateMouseEvent.call_args_list
        assert events[0].args[1] == _patch_quartz.kCGEventRightMouseDown
        assert events[1].args[1] == _patch_quartz.kCGEventRightMouseUp

    @patch("time.sleep")
    def test_click_middle(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.click(10, 20, button="middle")
        events = _patch_quartz.CGEventCreateMouseEvent.call_args_list
        assert events[0].args[1] == _patch_quartz.kCGEventOtherMouseDown
        assert events[1].args[1] == _patch_quartz.kCGEventOtherMouseUp

    @patch("time.sleep")
    def test_click_double_posts_four(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.click(10, 20, clicks=2)
        assert _patch_quartz.CGEventCreateMouseEvent.call_count == 4

    @patch("time.sleep")
    def test_move_to_posts_mouse_moved(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.move_to(30, 40)
        _patch_quartz.CGEventCreateMouseEvent.assert_called_once_with(
            None, _patch_quartz.kCGEventMouseMoved, (30, 40), _patch_quartz.kCGMouseButtonLeft
        )

    @patch("time.sleep")
    def test_scroll_vertical_small_amount(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.scroll(3)
        _patch_quartz.CGEventCreateScrollWheelEvent.assert_called_once()
        args = _patch_quartz.CGEventCreateScrollWheelEvent.call_args
        assert args.args[1] == _patch_quartz.kCGScrollEventUnitLine
        assert args.args[2] == 1  # wheel_count for vertical
        assert args.args[3] == 3  # vertical value

    @patch("time.sleep")
    def test_scroll_vertical_large_chunked(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.scroll(25)
        # 25 → two 10-chunks + one 5-remainder = 3 events
        assert _patch_quartz.CGEventCreateScrollWheelEvent.call_count == 3
        verticals = [c.args[3] for c in _patch_quartz.CGEventCreateScrollWheelEvent.call_args_list]
        assert verticals == [10, 10, 5]

    @patch("time.sleep")
    def test_hscroll_uses_wheel_count_two(self, _mock_sleep, _patch_quartz) -> None:
        macos_input.hscroll(4)
        args = _patch_quartz.CGEventCreateScrollWheelEvent.call_args
        assert args.args[2] == 2  # wheel_count for horizontal
        assert args.args[3] == 0  # vertical value zero
        assert args.args[4] == 4  # horizontal value

    @patch("time.sleep")
    @patch("myrm_agent_harness.toolkits.computer_use.backends.macos_input.position", return_value=_Point(10, 20))
    def test_drag_from_current_position(self, _mock_position, _mock_sleep, _patch_quartz) -> None:
        macos_input.drag(100, 200)
        events = _patch_quartz.CGEventCreateMouseEvent.call_args_list
        assert events[0].args[1] == _patch_quartz.kCGEventLeftMouseDown
        assert events[0].args[2] == (10, 20)
        assert events[-1].args[1] == _patch_quartz.kCGEventLeftMouseUp
        assert events[-1].args[2] == (110, 220)
        # down + steps + up; duration 0.5 → 5 steps
        assert len(events) == 1 + 5 + 1

    @patch("time.sleep")
    @patch("myrm_agent_harness.toolkits.computer_use.backends.macos_input.position", return_value=_Point(10, 20))
    def test_drag_zero_duration_single_step(self, _mock_position, _mock_sleep, _patch_quartz) -> None:
        macos_input.drag(10, 10, duration=0.0)
        events = _patch_quartz.CGEventCreateMouseEvent.call_args_list
        # down + 1 step + up
        assert len(events) == 3


class TestStateReads:
    def test_size_returns_dimensions(self, _patch_quartz) -> None:
        result = macos_input.size()
        assert result == _Size(width=1920, height=1080)
        _patch_quartz.CGMainDisplayID.assert_called_once()
        _patch_quartz.CGDisplayPixelsWide.assert_called_once_with(0)
        _patch_quartz.CGDisplayPixelsHigh.assert_called_once_with(0)

    def test_position_returns_point(self, _patch_quartz) -> None:
        result = macos_input.position()
        assert result == _Point(x=100, y=200)
        _patch_quartz.CGEventGetLocation.assert_called_once()
