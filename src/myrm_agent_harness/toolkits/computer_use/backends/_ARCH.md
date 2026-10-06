# backends/

## Overview
Platform-specific implementations of the ComputerBackend protocol. Provides macOS, Windows, and Linux desktop automation backends, with optional background-input support via `cua-driver`.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Computer use backends — re-exports ComputerBackend protocol. | — |
| protocols.py | Core | ComputerBackend protocol — abstract interface for platform backends. | ✅ |
| macos.py | Core | macOS backend — screencapture + Quartz CGEvent + NSScreen DPI + AX text; window-targeted capture (`screencapture -l`), foreground guard, post-event permission probe/request, EnhancedUI; `set_excluded_capture_window_titles` 帷幕排除通道注入；帷幕在屏时全局 HID 坐标类指针动作（click/mouse_move/scroll/drag）fail-closed（`_pointer_occluded`，定向投递与键盘不受影响）. | ✅ |
| macos_input.py | Core | macOS input primitives — Quartz CGEvent keyboard/mouse (replaces pyautogui); PID-targeted delivery via single post router; `has_input_target()` 判定当前任务是否定向投递. | ✅ |
| macos_background.py | Core | macOS background ops — window resolve, `screencapture -l` capture, foreground guard, post-event permission, EnhancedUI (crash-contained probe); `_capture_screen_excluding_titles` Quartz below-window 截图通道（帷幕窗排除，失败降级原 screencapture 路径）. | ✅ |
| windows.py | Core | Windows backend — mss + pyautogui + ctypes/user32 + uiautomation. | ✅ |
| linux.py | Core | Linux backend — scrot/gnome-screenshot + xdotool + DISPLAY auto-detection. | ✅ |
| cua_driver.py | Enhancement | Background-input backend via cua-driver MCP. Wraps a native backend. | ✅ |

Desktop backends cover macOS / Windows / Linux only. Android device control is a
separate toolkit (`toolkits/mobile_adb/`) with its own session, safety guard and @mref
parser — it is not a `ComputerBackend` implementation.

## Backend Selection (session.py → create_computer_session)

```
All platforms (macOS / Windows / Linux):
  cua-driver installed? ─── YES ──→ CuaDriverBackend(fallback=NativeBackend)
                        └── NO  ──→ NativeBackend (macOS: Quartz CGEvent / Windows: pyautogui / Linux: xdotool)
```

## cua-driver Integration

`CuaDriverBackend` uses the **proxy pattern**: input operations (click, type, key, scroll, drag, mouse_move) are routed to `cua-driver` via MCP stdio for background (focus-free) execution. Non-input operations (screenshot, screen_info, window_text, etc.) are delegated to the platform-native fallback backend.

If cua-driver fails for any individual action, it transparently falls back to the native backend for that operation. If cua-driver is not installed, it is never loaded.

**Install cua-driver**: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh)"`

## Key Dependencies

- `mss` (Windows screenshot capture)
- `pyobjc-framework-Quartz` (macOS input simulation — native CGEvent, avoids rubicon-objc arm64 bug)
- `pyautogui` (Windows input simulation — native fallback)
- `uiautomation` (Windows accessibility text extraction, optional)
- `xdotool` (Linux input simulation)
- `cua-driver` (macOS/Windows/Linux background input, optional, MIT license)
- `mcp` (Python MCP SDK, required only when cua-driver is used)
- `computer_use.capture_probe` + Pillow (optional decode) when `probe_capture=True`

## check_permissions() Protocol

All backends implement `check_permissions(*, probe_capture: bool = False) -> PermissionStatus`.

- **Default (`probe_capture=False`)**: OS grant signals only (`accessibility`, `screen_recording`).
  `screen_recording_capturable` stays `None`. `all_granted` ignores capturable.
- **`probe_capture=True`**: After grants, take a short capture sample and set
  `screen_recording_capturable` via shared `computer_use/capture_probe.py`
  (`png_bytes_look_capturable`). Doctor and FE Recheck use this path.
  `PermissionStatus.capture_ready` is True only when grants OK **and** capturable is True.
- Missing Pillow → capturable False (cannot verify; never fake ready).

| Platform | Accessibility Check | Screen Recording Check | Capture sample (when probing) |
|----------|-------------------|----------------------|-------------------------------|
| **macOS** | `AXIsProcessTrusted()` via ctypes **+ osascript** frontmost-process capability probe (osascript is a separate TCC binary) | `CGPreflightScreenCaptureAccess` via ctypes | `screencapture` PNG → luminance gate |
| **Windows** | Always granted (no TCC) | Always granted (no TCC) | mss/GDI PNG → luminance gate; deeplinks are OS/docs URLs only |
| **Linux** | Always granted (no per-app TCC) | Always granted | scrot/gnome-screenshot PNG → luminance gate |

macOS returns `settings_deeplinks` with `x-apple.systempreferences:` URLs for System Settings → Privacy & Security.
