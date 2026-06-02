# perception/

## Overview
Platform AX/UIA/AT-SPI snapshot capture, tree rendering, and element invoke dispatch for Semantic Desktop Control.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| ax_dispatch.py | Core | Platform routing: capture_snapshot, inspect_backend, invoke_element | ✅ |
| renderer.py | Core | AX tree text rendering for agent context | ✅ |
| macos_ax.py | Platform | macOS Accessibility API snapshot + invoke | ✅ |
| windows_ax.py | Platform | Windows UI Automation snapshot + invoke | ✅ |
| linux_ax.py | Platform | Linux AT-SPI snapshot; invoke stub with vision fallback message | ✅ |

## Dependencies

- `element_ref/types.py` (POS: shared @dref types)
- `backends/protocols.py` (POS: ComputerBackend protocol)
- Used by `desktop_session.py` (POS: semantic desktop orchestrator)

## Architecture Overview

Detailed design: [DESKTOP_SYSTEM.md](../DESKTOP_SYSTEM.md)
