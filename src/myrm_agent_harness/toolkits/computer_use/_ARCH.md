# computer_use/

## Overview
Semantic Desktop Control (SDC) toolkit. Enables AI agents to snapshot and interact
with native desktop applications via accessibility trees (@dref) with coordinate vision fallback.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports create_desktop_tools, create_desktop_session | ✅ |
| types.py | Config | Shared types: ComputerAction, DesktopInteractAction, ScreenInfo, ActionResult, PermissionStatus, ExecutionMode, ForegroundPermissionCallback, ComputerUseConfig | ✅ |
| app_identity.py | Core | Stable trust keys: `resolve_trust_key`, `trust_key_matches` (bundle_id / win exe / linux app id) | ✅ |
| safety.py | Core | Blocked key combos, dangerous type-text guardrails, sensitive app guard (incl. terminal/shell + SelfAppGuard via bundle_id / host names), foreground permission classification | ✅ |
| screenshot_processor.py | Core | Binary-search downsampling pipeline | ✅ |
| coordinate_scaler.py | Core | DPI-aware coordinate transformer | ✅ |
| som_overlay.py | Core | SOM numbered overlay on JPEG; agent path when `include_screenshot=True`, inspector refresh when screenshot captured; stable [N]↔@dref map (cap 80) | ✅ |
| session.py | Core | ComputerSession orchestrator (coordinate I/O, app + foreground gates, operation-scoped foreground waiver) | ✅ |
| desktop_session.py | Core | DesktopSession: AX snapshot, @dref registry, shared approval revalidation, DESKTOP_VIEW_UPDATE, export_inspector_snapshot | ✅ |
| desktop_agent_tools.py | Core | 3 LangChain tools: snapshot / interact / vision | ✅ |

| Submodule | Description |
|-----------|-------------|
| backends/ | Platform I/O: macOS, Windows, Linux |
| perception/ | AX tree capture, overlay role SSOT, renderer, ax_dispatch — see [perception/_ARCH.md](perception/_ARCH.md) |
| execution/ | BBox click healer fallback — see [execution/_ARCH.md](execution/_ARCH.md) |
| dref/ | @dref types, registry, errors (internal submodule) |

## Architecture

```
Agent → desktop_agent_tools (3 tools)
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
| desktop_snapshot_tool | AX tree with @dref IDs and app/window header; optional screenshot |
| desktop_interact_tool | Semantic action on @dref (click/fill/set_value/type/fill_credential/press/…) |
| desktop_vision_tool | Explicit screenshot/coordinate fallback |

## Key Design Decisions
    
1. **Semantic-first**: AX/UIA/AT-SPI tree → @dref interact; vision only when AX is empty
2. **View updates**: `desktop_snapshot` emits `DESKTOP_VIEW_UPDATE` via ToolProgressSink for frontend Desktop Inspector
3. **Safety in session**: Blocked key combos, dangerous type-text patterns, sensitive application guard (`is_sensitive_app`, including terminal/shell apps). Enforced in `desktop_snapshot`, `desktop_interact`, and `desktop_vision_action`
4. **Multimodal responses**: Vision capture/actions return text + JPEG image blocks
5. **Platform auto-detection**: reuses `detect_platform()` from code_execution
6. **Security & Re-validation**: shared `_revalidate_if_stale_after_approval()` after approval delay — interact verifies @dref; vision refreshes screenshot/scaler
7. **Credential Vault integration**: `fill_credential` resolves secrets without exposing them in LLM context
8. **Permission probing**: `DesktopSession.check_permissions()` + server `GET /webui/desktop/permissions`; Settings Doctor surfaces the same probe via `observability/diagnostics/probes.check_desktop_permissions_health` (`DesktopControl` component).
9. **Native API routing hints**: `inspect_foreground()` appends AppleScript/COM/D-Bus hints in snapshot recommendation text
10. **Background input (cua-driver)**: optional focus-free input proxy
11. **Desktop control gate**: `check_app_approval` on interact and vision mutating actions; uses snapshot meta or `inspect_backend()` fallback; `check_foreground_permission` for coordinate/healer paths with operation-scoped waiver after app approval. Server `DesktopControlGate` via `ForegroundPermissionCallback` (empty app fail-closed). LOCAL `background_strict`; sandbox auto-grants. SSE `desktop_control_approval_request` opens Desktop Inspector; resolve `POST /webui/desktop/approval/resolve`. Persist `{workspace}/.agent/desktop_control/approved_apps.json` keyed by stable `app_id` when available; list/revoke via `GET/DELETE /webui/desktop/trust/apps`
12. **Session lifecycle**: `ComputerSession.close()` on agent session end

## Key Dependencies

- `dref/` (@dref registry submodule)
- `core/security/credential_vault` (fill_credential vault resolution)
- `code_execution` (platform detection)
- `PIL`, `pyautogui`, platform AX libraries (see backends/)
- `cua-driver` (optional, background input on macOS/Windows/Linux)
