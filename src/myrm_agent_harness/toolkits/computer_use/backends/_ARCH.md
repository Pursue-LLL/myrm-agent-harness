# backends/

## Overview
Platform-specific implementations of the ComputerBackend protocol. Provides macOS, Windows, and Linux desktop automation backends, with optional background-input support via `cua-driver`.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Computer use backends — re-exports ComputerBackend protocol. | — |
| protocols.py | Core | ComputerBackend protocol — abstract interface for platform backends. | ✅ |
| macos.py | Core | macOS backend — screencapture + pyautogui + NSScreen DPI + AX text. | ✅ |
| windows.py | Core | Windows backend — mss + pyautogui + ctypes/user32 + uiautomation. | ✅ |
| linux.py | Core | Linux backend — scrot/gnome-screenshot + xdotool + DISPLAY auto-detection. | ✅ |
| cua_driver.py | Enhancement | Background-input backend via cua-driver MCP. Wraps a native backend. | ✅ |

## Backend Selection (session.py → create_computer_session)

```
All platforms (macOS / Windows / Linux):
  cua-driver installed? ─── YES ──→ CuaDriverBackend(fallback=NativeBackend)
                        └── NO  ──→ NativeBackend (pyautogui / xdotool)
```

## cua-driver Integration

`CuaDriverBackend` uses the **proxy pattern**: input operations (click, type, key, scroll, drag, mouse_move) are routed to `cua-driver` via MCP stdio for background (focus-free) execution. Non-input operations (screenshot, screen_info, window_text, etc.) are delegated to the platform-native fallback backend.

If cua-driver fails for any individual action, it transparently falls back to the native backend for that operation. If cua-driver is not installed, it is never loaded.

**Install cua-driver**: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh)"`

## Key Dependencies

- `mss` (Windows screenshot capture)
- `pyautogui` (macOS/Windows input simulation — native fallback)
- `uiautomation` (Windows accessibility text extraction, optional)
- `xdotool` (Linux input simulation)
- `cua-driver` (macOS/Windows/Linux background input, optional, MIT license)
- `mcp` (Python MCP SDK, required only when cua-driver is used)

## check_permissions() Protocol

All backends implement `check_permissions() -> PermissionStatus`. This probes OS-level
permissions required for desktop automation:

| Platform | Accessibility Check | Screen Recording Check |
|----------|-------------------|----------------------|
| **macOS** | AppleScript → `System Events` (detects TCC Accessibility denial) | `CGPreflightScreenCaptureAccess` via ctypes (detects TCC Screen Recording denial) |
| **Windows** | Always granted (no TCC) | Always granted (no TCC) |
| **Linux** | Always granted (X11/Wayland has no per-app permission gate) | Always granted |

macOS returns `settings_deeplinks` with `x-apple.systempreferences:` URLs for one-click
navigation to System Settings → Privacy & Security.
