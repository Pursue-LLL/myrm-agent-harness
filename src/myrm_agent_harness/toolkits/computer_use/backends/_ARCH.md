# backends/

## Overview
Platform-specific implementations of the ComputerBackend protocol. Provides macOS, Windows, and Linux desktop automation backends.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Computer use backends — re-exports ComputerBackend protocol. | — |
| linux.py | Core | Linux backend — scrot/gnome-screenshot + xdotool + DISPLAY auto-detection. | ✅ |
| macos.py | Core | macOS backend — screencapture + pyautogui + NSScreen DPI + AX text. | ✅ |
| windows.py | Core | Windows backend — mss + pyautogui + ctypes/user32 + uiautomation. | ✅ |
| protocols.py | Core | ComputerBackend protocol — abstract interface for platform backends. | ✅ |

## Key Dependencies

- `mss` (Windows screenshot capture)
- `pyautogui` (macOS/Windows input simulation)
- `uiautomation` (Windows accessibility text extraction, optional)
- `xdotool` (Linux input simulation)

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
