# perception/

## Overview
Platform AX/UIA/AT-SPI snapshot capture, tree rendering, element invoke dispatch, and native API routing hints for Semantic Desktop Control.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| ax_dispatch.py | Core | Platform routing: capture_snapshot, inspect_backend, invoke_element | ✅ |
| renderer.py | Core | AX tree text rendering for agent context | ✅ |
| macos_ax.py | Platform | macOS Accessibility API snapshot + invoke + native API routing hints | ✅ |
| windows_ax.py | Platform | Windows UI Automation snapshot + invoke + COM/PowerShell routing hints | ✅ |
| linux_ax.py | Platform | Linux AT-SPI snapshot; invoke stub + D-Bus routing hints | ✅ |

## Dependencies

- `element_ref/types.py` (POS: shared @dref types)
- `backends/protocols.py` (POS: ComputerBackend protocol)
- Used by `desktop_session.py` (POS: semantic desktop orchestrator)

## Key Design: Native API Routing Hints

Each platform's `inspect_foreground()` identifies whether the frontmost app supports native automation (AppleScript/COM/D-Bus) and appends a routing hint to the `recommendation` field. This guides the Agent to prefer `bash_code_execute_tool` with native scripts for data retrieval or bulk actions — faster and more reliable than GUI interaction — without adding new tools or breaking prompt cache.

## Architecture Overview

Detailed design: [DESKTOP_SYSTEM.md](../DESKTOP_SYSTEM.md)
