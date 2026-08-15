"""macOS 原生键鼠输入原语 — Quartz CGEvent 直接实现。

替代 pyautogui：pyautogui 在 macOS 底层即使用 Quartz.CGEvent，但其顶层 import
会拉入 mouseinfo → rubicon-objc，后者在 arm64（Apple Silicon）上因引用不存在的
`objc_msgSendSuper_stret` 符号而无法导入（上游 rubicon-objc 缺陷，0.5.6 未修复）。
本模块直接使用 pyobjc Quartz 原语，功能等价且绕开该缺陷。

[INPUT]
- types::ModifierKey（经 backends/macos.py 映射为 Quartz 键名后传入）

[OUTPUT]
- 键鼠模拟原语：key_down/key_up/press/hotkey/write/click/move_to/scroll/hscroll/drag
- 状态读取原语：size/position

[POS]
macOS 输入原语。仅被 backends/macos.py 引用，随 computer-use extra 安装。
"""

from __future__ import annotations

import time
from typing import NamedTuple

# pyautogui 在 macOS 上与 pyautogui.DARWIN_CATCH_UP_TIME 保持一致的事件间隙，
# 让 OS 在键/鼠事件之间有足够时间处理，避免过快事件被合并。
_CATCH_UP_TIME = 0.02

_SHIFT_CHARACTERS = '~!@#$%^&*()_+{}|:"<>?'

# macOS 虚拟键码表（kVK_*），与 pyautogui._pyautogui_osx.keyboardMapping 一致。
_KEYCODES: dict[str, int] = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11,
    "1": 0x12, "!": 0x12, "2": 0x13, "@": 0x13, "3": 0x14, "#": 0x14,
    "4": 0x15, "$": 0x15, "6": 0x16, "^": 0x16, "5": 0x17, "%": 0x17,
    "=": 0x18, "+": 0x18, "9": 0x19, "(": 0x19, "7": 0x1A, "&": 0x1A,
    "-": 0x1B, "_": 0x1B, "8": 0x1C, "*": 0x1C, "0": 0x1D, ")": 0x1D,
    "]": 0x1E, "}": 0x1E, "o": 0x1F, "u": 0x20, "[": 0x21, "{": 0x21,
    "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "'": 0x27, '"': 0x27,
    "k": 0x28, ";": 0x29, ":": 0x29, "\\": 0x2A, "|": 0x2A, ",": 0x2B,
    "<": 0x2B, "/": 0x2C, "?": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F,
    ">": 0x2F, "`": 0x32, "~": 0x32, " ": 0x31, "space": 0x31,
    "\r": 0x24, "\n": 0x24, "enter": 0x24, "return": 0x24,
    "\t": 0x30, "tab": 0x30, "backspace": 0x33, "\b": 0x33,
    "esc": 0x35, "escape": 0x35,
    "command": 0x37, "shift": 0x38, "shiftleft": 0x38, "capslock": 0x39,
    "option": 0x3A, "optionleft": 0x3A, "alt": 0x3A, "altleft": 0x3A,
    "ctrl": 0x3B, "ctrlleft": 0x3B, "shiftright": 0x3C, "optionright": 0x3D,
    "ctrlright": 0x3E, "fn": 0x3F,
    "f17": 0x40, "volumeup": 0x48, "volumedown": 0x49, "volumemute": 0x4A,
    "f18": 0x4F, "f19": 0x50, "f20": 0x5A, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f3": 0x63, "f8": 0x64, "f9": 0x65, "f11": 0x67,
    "f13": 0x69, "f16": 0x6A, "f14": 0x6B, "f10": 0x6D, "f12": 0x6F,
    "f15": 0x71, "help": 0x72, "home": 0x73, "pageup": 0x74, "pgup": 0x74,
    "del": 0x75, "delete": 0x75, "f4": 0x76, "end": 0x77, "f2": 0x78,
    "pagedown": 0x79, "pgdn": 0x79, "f1": 0x7A, "left": 0x7B,
    "right": 0x7C, "down": 0x7D, "up": 0x7E,
    "yen": 0x5D, "eisu": 0x66, "kana": 0x68,
}

# 大写字母映射到同键码（与 pyautogui 一致）
for _c in "abcdefghijklmnopqrstuvwxyz":
    _KEYCODES[_c.upper()] = _KEYCODES[_c]


class _Size(NamedTuple):
    width: int
    height: int


class _Point(NamedTuple):
    x: int
    y: int


def _is_shift_character(char: str) -> bool:
    """判断字符是否需要 Shift 修饰（大写字母或 shift 标点）。"""
    return char.isupper() or char in _SHIFT_CHARACTERS


def _post_key_event(keycode: int, is_down: bool) -> None:
    from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap

    event = CGEventCreateKeyboardEvent(None, keycode, is_down)
    CGEventPost(kCGHIDEventTap, event)


def _post_mouse_event(event_type: int, x: int, y: int, button: int) -> None:
    from Quartz import CGEventCreateMouseEvent, CGEventPost, kCGHIDEventTap

    event = CGEventCreateMouseEvent(None, event_type, (x, y), button)
    CGEventPost(kCGHIDEventTap, event)


def _post_scroll(amount: int, vertical: bool) -> None:
    from Quartz import CGEventCreateScrollWheelEvent, CGEventPost, kCGHIDEventTap, kCGScrollEventUnitLine

    wheel_count = 1 if vertical else 2
    # 与 pyautogui 一致：每 10 格一段投递，避免大数值被应用忽略。
    for _ in range(abs(amount) // 10):
        step = 10 if amount > 0 else -10
        event = CGEventCreateScrollWheelEvent(
            None, kCGScrollEventUnitLine, wheel_count,
            step if vertical else 0,
            0 if vertical else step,
        )
        CGEventPost(kCGHIDEventTap, event)
    remainder = amount % 10 if amount >= 0 else -1 * ((-amount) % 10)
    event = CGEventCreateScrollWheelEvent(
        None, kCGScrollEventUnitLine, wheel_count,
        remainder if vertical else 0,
        0 if vertical else remainder,
    )
    CGEventPost(kCGHIDEventTap, event)


def key_down(key: str) -> None:
    """按下指定键（shift 字符自动附带 Shift 修饰）。"""
    if _is_shift_character(key):
        _post_key_event(_KEYCODES["shift"], True)
        time.sleep(_CATCH_UP_TIME)
    _post_key_event(_KEYCODES[key], True)
    time.sleep(_CATCH_UP_TIME)


def key_up(key: str) -> None:
    """释放指定键（shift 字符自动附带 Shift 修饰）。"""
    _post_key_event(_KEYCODES[key], False)
    time.sleep(_CATCH_UP_TIME)
    if _is_shift_character(key):
        _post_key_event(_KEYCODES["shift"], False)
        time.sleep(_CATCH_UP_TIME)


def press(key: str) -> None:
    """按下并释放单个键。"""
    key_down(key)
    key_up(key)


def hotkey(*keys: str) -> None:
    """按顺序按下全部键，再逆序释放（组合快捷键）。"""
    for key in keys:
        key_down(key)
    for key in reversed(keys):
        key_up(key)


def write(text: str, interval: float = 0.0) -> None:
    """逐字符输入文本（CGEventKeyboardSetUnicodeString，任意 Unicode 均可靠）。"""
    from Quartz import (
        CGEventCreate,
        CGEventCreateKeyboardEvent,
        CGEventKeyboardSetUnicodeString,
        CGEventPost,
        kCGHIDEventTap,
    )

    source = CGEventCreate(None)
    for char in text:
        down = CGEventCreateKeyboardEvent(source, 0, True)
        CGEventKeyboardSetUnicodeString(down, 1, char)
        CGEventPost(kCGHIDEventTap, down)
        up = CGEventCreateKeyboardEvent(source, 0, False)
        CGEventPost(kCGHIDEventTap, up)
        if interval:
            time.sleep(interval)


def click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    """在 (x, y) 处点击指定鼠标按键，支持连击次数。"""
    from Quartz import (
        kCGEventLeftMouseDown,
        kCGEventLeftMouseUp,
        kCGEventOtherMouseDown,
        kCGEventOtherMouseUp,
        kCGEventRightMouseDown,
        kCGEventRightMouseUp,
        kCGMouseButtonCenter,
        kCGMouseButtonLeft,
        kCGMouseButtonRight,
    )

    down_type, up_type, cg_button = {
        "left": (kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft),
        "right": (kCGEventRightMouseDown, kCGEventRightMouseUp, kCGMouseButtonRight),
        "middle": (kCGEventOtherMouseDown, kCGEventOtherMouseUp, kCGMouseButtonCenter),
    }[button]
    for _ in range(clicks):
        _post_mouse_event(down_type, x, y, cg_button)
        _post_mouse_event(up_type, x, y, cg_button)
        time.sleep(_CATCH_UP_TIME)


def move_to(x: int, y: int) -> None:
    """移动鼠标到 (x, y)。"""
    from Quartz import kCGEventMouseMoved, kCGMouseButtonLeft

    _post_mouse_event(kCGEventMouseMoved, x, y, kCGMouseButtonLeft)
    time.sleep(_CATCH_UP_TIME)


def scroll(amount: int) -> None:
    """垂直滚动指定格数（正值向上，负值向下）。"""
    _post_scroll(amount, vertical=True)


def hscroll(amount: int) -> None:
    """水平滚动指定格数（正值向左，负值向右）。"""
    _post_scroll(amount, vertical=False)


def drag(dx: int, dy: int, duration: float = 0.5) -> None:
    """从当前位置按住左键拖拽 (dx, dy)，duration 控制平滑时长。"""
    from Quartz import kCGEventLeftMouseDown, kCGEventLeftMouseDragged, kCGEventLeftMouseUp, kCGMouseButtonLeft

    start = position()
    end_x, end_y = start.x + dx, start.y + dy
    _post_mouse_event(kCGEventLeftMouseDown, start.x, start.y, kCGMouseButtonLeft)
    steps = max(1, int(duration / 0.1))
    for i in range(1, steps + 1):
        x = start.x + (end_x - start.x) * i // steps
        y = start.y + (end_y - start.y) * i // steps
        _post_mouse_event(kCGEventLeftMouseDragged, x, y, kCGMouseButtonLeft)
        time.sleep(duration / steps)
    _post_mouse_event(kCGEventLeftMouseUp, end_x, end_y, kCGMouseButtonLeft)


def size() -> _Size:
    """主显示器尺寸（逻辑像素，与 screencapture -C 的 Retina 比例一致）。"""
    from Quartz import CGDisplayPixelsHigh, CGDisplayPixelsWide, CGMainDisplayID

    main = CGMainDisplayID()
    return _Size(
        width=int(CGDisplayPixelsWide(main)),
        height=int(CGDisplayPixelsHigh(main)),
    )


def position() -> _Point:
    """当前鼠标位置（CG 全局坐标，左上原点，与截图坐标系一致）。"""
    from Quartz import CGEventCreate, CGEventGetLocation

    loc = CGEventGetLocation(CGEventCreate(None))
    return _Point(x=int(loc.x), y=int(loc.y))
