# Semantic Desktop Control (SDC) System Design

> Hybrid native desktop automation: accessibility tree + @dref semantic interact, with explicit coordinate vision fallback.

---

## Design Goals

1. **Agent-friendly**: @dref element references from AX/UIA/AT-SPI trees reduce token cost vs full-screen screenshots every step
2. **Semantic-first**: Prefer `desktop_interact_tool(ref=@dref)` over coordinate guessing
3. **Explicit fallback**: `desktop_vision_tool` for canvas-only UIs, empty AX trees, or failed semantic invoke
4. **WebUI parity**: Mirror browser inspector via `DESKTOP_VIEW_UPDATE` SSE + `/webui/desktop/snapshot` REST refresh
5. **Safety**: Three guardrail types in `safety.py` — blocked key combos, dangerous type-text patterns, and sensitive application guard (`is_sensitive_app`, including terminal/shell apps and SelfAppGuard for Myrm/Cursor host UI via bundle_id + host names). Enforced in `desktop_snapshot`, `desktop_interact`, and `desktop_vision_action`

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LangChain Tools (3)                      │
│  desktop_snapshot | desktop_interact | desktop_vision       │
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
│      CuaDriverBackend (optional, macOS / Windows / Linux)     │
│  Background input via cua-driver MCP (focus-free)           │
│  PID re-resolved per operation; fallback on any error       │
│  ComputerSession.close() releases MCP subprocess on exit   │
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
desktop_snapshot_tool
    ↓ AX tree with @dref IDs, app/window header (+ optional screenshot with [N] SOM labels) + browser soft-routing hint
desktop_interact_tool(ref=@dref, action=...)
    ↓ per-app approval gate → AX invoke → bbox healer fallback → text-only follow-up snapshot
desktop_vision_tool (only when AX empty or interact failed)
    ↓ per-app approval gate → foreground permission gate → stale refresh → coordinate actions
```

---

## Core Components

| Component | Location | Role |
|-----------|----------|------|
| `DesktopSession` | `desktop_session.py` | Orchestrator: registry, snapshot, interact, view updates |
| `create_desktop_tools` | `desktop_agent_tools.py` | LangChain tool factory |
| `DRefRegistry` | `computer_use/dref/registry.py` | Session-scoped @dref map |
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
| Linux | AT-SPI (pyatspi) | ✅ | ✅ |

---

## Frontend Integration

| Channel | Payload |
|---------|---------|
| SSE `DESKTOP_VIEW_UPDATE` | screenshot_base64 (SOM-labeled when multimodal agent snapshot or inspector refresh), refs (BBox overlay + `nth` when SOM active), needs_permission |
| SSE `DESKTOP_CONTROL_APPROVAL_REQUEST` | Per-app / foreground approval card in Desktop Inspector |
| REST `GET /webui/desktop/snapshot` | Same shape; called on `desktop_*` TOOL_END + manual refresh |
| REST `POST /webui/desktop/approval/resolve` | Resolve pending desktop control approval |
| Desktop Inspector | `DesktopLiveView` auto-opens on approval SSE; `DesktopControlApprovalBanner` for Allow/Deny |

Server wiring: `agent._desktop_session` → `AgentGateway.get_active_desktop_session()`.

---

## Diagnostics

| Surface | Role |
|---------|------|
| `GET /webui/desktop/permissions` | On-demand OS permission probe (Accessibility, Screen Recording); temporary session closed after probe |
| `CuPermissionInline` (Agent config) | Inline status when `computer_use` is enabled locally |
| Settings Doctor `DesktopControl` probe | Same probe via `check_desktop_permissions_health()` in `observability/diagnostics/probes.py` |
| Server regression | `myrm-agent-server/tests/api/health/test_doctor.py::test_desktop_control_probe_in_doctor`; `tests/api/webui/test_desktop_permissions.py` (probe session close) |
| Frontend vitest | `DoctorDashboard.desktopControlWarn.test.tsx`; `CuPermissionInline.test.tsx`; `DesktopPermissionsCard.test.tsx` (5 cases); `DesktopControlApprovalBanner.test.tsx`; `DesktopLiveView.permissionBanner.test.tsx`; `lib/desktop/permissionDeepLink.test.ts` (6 files, 22 cases) |
| Deeplink SSOT | `myrm-agent-frontend/src/lib/desktop/permissionDeepLink.ts` |
| Open semantics | Settings `DesktopPermissionsCard` → `openPermissionDeepLink`（deeplink fallback）；Doctor / Agent inline / Inspector → `openPermissionDeepLinkWithGuideFallback(url, platform)`（平台指南 fallback） |
| Trusted apps | `GET/DELETE /webui/desktop/trust/apps` + Settings trusted-apps section（加载失败显示重试，不伪装空列表） |
| Chrome E2E | `tests/e2e/test_desktop_control_approval_chrome_e2e.py` + `tests/e2e/desktop_approval/` — allow_once / allow_session / allow_always→revoke；Darwin：`./myrm test -m chrome_e2e_desktop …` 或 maintainer signoff desktop phase |
| Chrome E2E attach gate | `tests/support/e2e_runtime_guard.py::assert_chrome_attach_health` — shared-attach lane only; item runtimes skip (private preflight already ran) |

Channel security: IM strips `!desktop_*`; Cron denies `desktop_capture` / `desktop_control` (see [SECURITY_SYSTEM.md](../../agent/security/SECURITY_SYSTEM.md)).

---

## Agent Prompt Rules

Injected via `DESKTOP_CONTROL_RULES` in `shared_rules.py` when `enable_computer_use`:

- Workflow order: snapshot → interact
- Prefer @dref; use `set_value` for atomic field replacement; use vision only when AX is empty or interact failed
- macOS permission: ask user to grant Accessibility before retry
- Per-app first approval via Web UI (`DesktopControlApprovalBanner`)
- Native API routing: snapshot recommendation may suggest `bash_code_execute_tool` for scriptable apps

---

## Known Limits (Roadmap Scope)

| Item | Status |
|------|--------|
| Linux AT-SPI invoke | ✅ implemented (pyatspi doAction/EditableText/grabFocus) |
| Desktop control gate (server) | ✅ `DesktopControlGate` + SSE approval card. Local monorepo: `./myrm ready` (editable harness; no PyPI). Release/CI: harness tag → `./myrm harness sync-lock` → commit `uv.lock` before `--frozen` |
| Stream E2E tests | ✅ `test_desktop_control_approval_chrome_e2e.py` + `tests/e2e/desktop_approval/` — `@pytest.mark.chrome_e2e_desktop`；allow_once + allow_always→Settings revoke；strict `\\bDONE\\b`；Darwin maintainer desktop phase 或 `./myrm test -m chrome_e2e_desktop` |
| Onboarding hint when computer_use enabled | implemented (toggle + tooltip + empty state) |
| Native API routing hints | implemented (macOS/Windows/Linux) |

---

## References

- Browser parity: [BROWSER_SYSTEM.md](../browser/BROWSER_SYSTEM.md)
- Module index: [_ARCH.md](_ARCH.md)
- 模块索引：[_ARCH.md](_ARCH.md)（hybrid desktop 规划仅在私有 vortexai `temp-docs/`，非本仓路径）
