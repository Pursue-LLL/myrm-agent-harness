# computer_use/

## Overview
Semantic Desktop Control (SDC) toolkit. Enables AI agents to inspect, snapshot, and interact
with native desktop applications via accessibility trees (@dref) with coordinate vision fallback.

Detailed design: [DESKTOP_SYSTEM.md](DESKTOP_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports create_desktop_tools, create_desktop_session | ✅ |
| types.py | Config | Shared types: ComputerAction, ScreenInfo, ActionResult, ComputerUseConfig | ✅ |
| safety.py | Core | Blocked key combos and dangerous type-text guardrails | ✅ |
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
                  → ComputerBackend (Protocol)
```

## Tool Surface

| Tool | Purpose |
|------|---------|
| desktop_inspect_tool | Foreground app/window metadata + workflow hint |
| desktop_snapshot_tool | AX tree with @dref IDs; optional screenshot |
| desktop_interact_tool | Semantic action on @dref (click/fill/type/press/…) |
| desktop_vision_tool | Explicit screenshot/coordinate fallback |

## Key Design Decisions
    
1. **Semantic-first**: AX/UIA/AT-SPI tree → @dref interact; vision only when AX is empty
2. **View updates**: `desktop_snapshot` emits `DESKTOP_VIEW_UPDATE` via ToolProgressSink for frontend Desktop Inspector
3. **Safety in session**: `desktop_vision_action` enforces blocked keys and dangerous type patterns
4. **Multimodal responses**: Vision capture/actions return text + JPEG image blocks
5. **Platform auto-detection**: reuses `detect_platform()` from code_execution
6. **Security & Re-validation**: `desktop_interact` implements a Time-of-Check to Time-of-Use (TOCTOU) defense by re-capturing and verifying the @dref state if the action was delayed (e.g. by Human-in-the-Loop approval interception).

## Key Dependencies

- `element_ref/` (shared @dref registry)
- `code_execution` (platform detection)
- `PIL`, `pyautogui`, platform AX libraries (see backends/)
