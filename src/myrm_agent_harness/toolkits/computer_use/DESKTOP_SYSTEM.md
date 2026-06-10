# Semantic Desktop Control (SDC) System Design

> Hybrid native desktop automation: accessibility tree + @dref semantic interact, with explicit coordinate vision fallback.

---

## Design Goals

1. **Agent-friendly**: @dref element references from AX/UIA/AT-SPI trees reduce token cost vs full-screen screenshots every step
2. **Semantic-first**: Prefer `desktop_interact_tool(ref=@dref)` over coordinate guessing
3. **Explicit fallback**: `desktop_vision_tool` for canvas-only UIs, empty AX trees, or failed semantic invoke
4. **WebUI parity**: Mirror browser inspector via `DESKTOP_VIEW_UPDATE` SSE + `/webui/desktop/snapshot` REST refresh
5. **Safety**: Blocked key combos and dangerous type patterns enforced in `desktop_vision_action`

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LangChain Tools (4)                      │
│  desktop_inspect | desktop_snapshot | desktop_interact      │
│  desktop_vision                                             │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                    DesktopSession                           │
│  ┌──────────────┬──────────────┬──────────────┬──────────┐ │
│  │ DRefRegistry │ perception/  │ execution/   │Computer  │ │
│  │  (@dref)     │ AX capture   │ bbox healer  │Session   │ │
│  └──────────────┴──────────────┴──────────────┴──────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│              ComputerBackend (macOS / Windows / Linux)        │
│  Screenshot + coordinate I/O via pyautogui / xdotool        │
└─────────────────────────────────────────────────────────────┘
```

---

## Workflow

```
desktop_inspect_tool
    ↓ foreground app/window metadata + permission hint + native API routing hint
desktop_snapshot_tool
    ↓ AX tree with @dref IDs (+ optional screenshot) + browser soft-routing hint
desktop_interact_tool(ref=@dref, action=...)
    ↓ AX invoke → bbox healer fallback → text-only follow-up snapshot
desktop_vision_tool (only when AX empty or interact failed)
    ↓ explicit screenshot + coordinate actions
```

---

## Core Components

| Component | Location | Role |
|-----------|----------|------|
| `DesktopSession` | `desktop_session.py` | Orchestrator: registry, snapshot, interact, view updates |
| `create_desktop_tools` | `desktop_agent_tools.py` | LangChain tool factory |
| `DRefRegistry` | `element_ref/registry.py` | Session-scoped @dref map |
| `perception/` | `ax_dispatch.py`, platform AX | Capture AX tree, invoke elements |
| `execution/healer.py` | BBox click fallback | When AX invoke fails |
| `ComputerSession` | `session.py` | Screenshot + coordinate I/O |
| `backends/` | Platform I/O | macOS, Windows, Linux |

---

## Platform Support

| Platform | AX Snapshot | AX Invoke | Vision Fallback |
|----------|-------------|-----------|-----------------|
| macOS | Accessibility API | ✅ | ✅ |
| Windows | UI Automation | ✅ | ✅ |
| Linux | AT-SPI (pyatspi) | ⚠️ stub → vision | ✅ |

---

## Frontend Integration

| Channel | Payload |
|---------|---------|
| SSE `DESKTOP_VIEW_UPDATE` | screenshot_base64, refs (BBox overlay), needs_permission |
| REST `GET /webui/desktop/snapshot` | Same shape; called on `desktop_*` TOOL_END + manual refresh |
| Desktop Inspector | `DesktopLiveView` + `ElementOverlay` (mirrors browser-inspector); toggle visible when `computer_use` tool enabled |

Server wiring: `agent._desktop_session` → `AgentGateway.get_active_desktop_session()`.

---

## Agent Prompt Rules

Injected via `DESKTOP_CONTROL_RULES` in `shared_rules.py` when `enable_computer_use`:

- Workflow order: inspect → snapshot → interact
- Prefer @dref; use vision only when AX is empty or interact failed
- macOS permission: ask user to grant Accessibility before retry
- Native API routing: when inspect detects a scriptable app, prefer bash_tool with native commands for data-heavy tasks

---

## Known Limits (Roadmap Scope)

| Item | Status | Roadmap |
|------|--------|---------|
| Linux AT-SPI invoke | stub | platform parity |
| `verify_goal` post-condition | field only | #7 |
| Stream E2E tests | not covered | future |
| Onboarding hint when computer_use enabled | implemented (toggle + tooltip + empty state) |
| Native API routing hints | implemented (macOS/Windows/Linux) | #2 done |

---

## References

- Browser parity: [BROWSER_SYSTEM.md](../browser/BROWSER_SYSTEM.md)
- Module index: [_ARCH.md](_ARCH.md)
- 模块索引：[_ARCH.md](_ARCH.md)（hybrid desktop 规划仅在私有 vortexai `temp-docs/`，非本仓路径）
