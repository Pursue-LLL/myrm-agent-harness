# computer_use/

## Overview
Semantic Desktop Control (SDC) toolkit. Enables AI agents to inspect, snapshot, and interact
with native desktop applications via accessibility trees (@dref) with coordinate vision fallback.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports create_desktop_tools, create_desktop_session | ✅ |
| types.py | Config | Shared types: ComputerAction, DesktopInteractAction, ScreenInfo, ActionResult, PermissionStatus, ComputerUseConfig | ✅ |
| safety.py | Core | Blocked key combos, dangerous type-text guardrails, and sensitive app guard | ✅ |
| screenshot_processor.py | Core | Binary-search downsampling pipeline | ✅ |
| coordinate_scaler.py | Core | DPI-aware coordinate transformer | ✅ |
| session.py | Core | ComputerSession orchestrator (coordinate I/O) | ✅ |
| desktop_session.py | Core | DesktopSession: AX snapshot, @dref registry, DESKTOP_VIEW_UPDATE, export_inspector_snapshot | ✅ |
| desktop_agent_tools.py | Core | 4 LangChain tools: inspect / snapshot / interact / vision | ✅ |

| Submodule | Description |
|-----------|-------------|
| backends/ | Platform I/O: macOS, Windows, Linux |
| perception/ | AX tree capture, renderer, ax_dispatch — see [perception/_ARCH.md](perception/_ARCH.md) |
| execution/ | BBox click healer fallback — see [execution/_ARCH.md](execution/_ARCH.md) |
| ../element_ref/ | Shared @dref types, registry, errors |

## Architecture

```
Agent → desktop_agent_tools (4 tools)
          → DesktopSession (semantic orchestrator)
              → DRefRegistry (@dref)
              → perception/ (AX snapshot + invoke)
              → execution/healer (bbox fallback)
              → ComputerSession (screenshot + coordinate I/O)
                  → CuaDriverBackend (background input proxy, optional)
                      → cua-driver MCP (SkyLight SPIs / Touch Injection)
                  → ComputerBackend (Protocol: macOS / Windows / Linux)
```

## Tool Surface

| Tool | Purpose |
|------|---------|
| desktop_inspect_tool | Foreground app/window metadata + workflow hint |
| desktop_snapshot_tool | AX tree with @dref IDs; optional screenshot |
| desktop_interact_tool | Semantic action on @dref (click/fill/type/fill_credential/press/…) |
| desktop_vision_tool | Explicit screenshot/coordinate fallback |

## Key Design Decisions
    
1. **Semantic-first**: AX/UIA/AT-SPI tree → @dref interact; vision only when AX is empty
2. **View updates**: `desktop_snapshot` emits `DESKTOP_VIEW_UPDATE` via ToolProgressSink for frontend Desktop Inspector
3. **Safety in session**: Three guardrail types — blocked key combos, dangerous type-text patterns, and sensitive application guard (`is_sensitive_app`). All three check points in `desktop_snapshot`, `desktop_interact`, and `desktop_vision_action` enforce the sensitive app blocklist against the foreground `app_name`
4. **Multimodal responses**: Vision capture/actions return text + JPEG image blocks
5. **Platform auto-detection**: reuses `detect_platform()` from code_execution
6. **Security & Re-validation**: `desktop_interact` implements a Time-of-Check to Time-of-Use (TOCTOU) defense by re-capturing and verifying the @dref state if the action was delayed (e.g. by Human-in-the-Loop approval interception). `desktop_vision_action` implements a "hard fuse" that blocks stale coordinate actions if delayed by more than 5 seconds.
7. **Credential Vault integration**: `fill_credential` action resolves password/TOTP from the global CredentialVault by label, then delegates to the `fill` AX action. Secrets never appear in LLM context.
8. **Permission probing**: `DesktopSession.check_permissions()` delegates to backend `check_permissions()` to probe OS-level TCC permissions (macOS Accessibility + Screen Recording). Server exposes `GET /webui/desktop/permissions` for frontend proactive guidance.
9. **Native API routing hints**: `inspect_foreground()` detects whether the frontmost app supports native scripting (AppleScript/COM/D-Bus) and appends a routing hint to `recommendation`. This guides the Agent to prefer `bash_code_execute_tool` with native commands for data-heavy or bulk tasks — no new tools needed, no prompt cache impact.

10. **Background input (cua-driver)**: `CuaDriverBackend` wraps the native backend as a proxy. Input operations route to `cua-driver` MCP for focus-free execution; non-input operations delegate to the native backend. PID is re-resolved on every input operation to ensure cross-application correctness. Falls back transparently to native backend per-operation on any cua-driver error.
11. **Session lifecycle**: `ComputerSession.close()` releases backend resources (e.g. cua-driver MCP subprocess). Server layer calls `close()` when the agent session ends to prevent subprocess leaks.

## Key Dependencies

- `element_ref/` (shared @dref registry)
- `security/credential_vault` (fill_credential vault resolution)
- `code_execution` (platform detection)
- `PIL`, `pyautogui`, platform AX libraries (see backends/)
- `cua-driver` (optional, background input on macOS/Windows/Linux)
