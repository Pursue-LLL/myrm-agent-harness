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
