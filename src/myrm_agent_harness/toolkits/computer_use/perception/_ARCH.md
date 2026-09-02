# perception/

## Overview
Platform AX/UIA/AT-SPI snapshot capture, tree rendering, incremental diff, element invoke dispatch, and native API routing hints for Semantic Desktop Control.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Platform AX/UIA/AT-SPI perception package | — |
| ax_dispatch.py | Core | Platform routing: capture_snapshot, inspect_backend, invoke_element | ✅ |
| ax_diff.py | Core | Incremental AX tree diff: `compute_ref_diff` compares two snapshots via (role, name) identity matching + bbox proximity, produces `RefDiff` with 4-layer full-view fallback (first snapshot / app change / high change ratio / low identity confidence) | ✅ |
| overlay_roles.py | Core | Cross-platform overlay role SSOT for SOM + Inspector | ✅ |
| renderer.py | Core | AX tree text rendering: `render_snapshot_tree` (full) + `render_diff_tree` (incremental diff with +/~/- markers); optional `[N]` SOM line prefixes | ✅ |
| macos_ax.py | Platform | macOS Accessibility API snapshot + invoke + native API routing hints; targeted capture by app name (exact name with contains fallback, auto-restores minimized windows, bypasses frontmost; not found falls back to foreground with `scope` reflecting `foreground`); `refs_for_view_update` fills `nth` from SOM map | ✅ |
| windows_ax.py | Platform | Windows UI Automation snapshot + invoke + COM/PowerShell routing hints; targeted capture by process name via shared `_locate_window` with auto-restore of minimized windows and rendering settle wait (capture and invoke reuse it for index consistency) | ✅ |
| linux_ax.py | Platform | Linux AT-SPI snapshot + invoke (pyatspi doAction/EditableText/grabFocus) + D-Bus routing hints; targeted capture scoped to a matching application (shared by capture and invoke) | ✅ |

## Dependencies

- `computer_use/dref/types.py` (POS: @dref types)
- `computer_use/dref/registry.py` (POS: @dref registry; diff reads current refs via `all_refs()`/`meta` before `replace()`)
- `computer_use/backends/protocols.py` (POS: ComputerBackend protocol)
- Used by `desktop_session.py` (POS: semantic desktop orchestrator)

## Key Design: Incremental AX Tree Diff

`ax_diff.py` reduces follow-up snapshot token cost by 80%+ in continuous-interact scenarios.
When `desktop_interact` completes, the follow-up snapshot compares current refs against previous
refs via `compute_ref_diff`. If the diff is reliable (same app, sufficient identity confidence,
low change ratio), only changed entries (+added, ~updated, -removed) are rendered to the agent
context. Four fallback conditions automatically revert to full-tree rendering.

## Key Design: Native API Routing Hints

Each platform's `inspect_foreground()` builds the `recommendation` field from `_SNAPSHOT_RECOMMENDATION_BASE` (snapshot-first workflow plus `scope='target'` guidance for acting on a background app) and appends a routing hint when the frontmost app supports native automation (AppleScript/COM/D-Bus). The routing hint guides the Agent to prefer `bash_code_execute_tool` with native scripts for data retrieval or bulk actions — faster and more reliable than GUI interaction — without adding new tools or breaking prompt cache.

## Architecture Overview

Detailed design: [DESKTOP_SYSTEM.md](../DESKTOP_SYSTEM.md)
