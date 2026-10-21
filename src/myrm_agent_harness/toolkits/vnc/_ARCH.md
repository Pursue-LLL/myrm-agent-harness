# vnc/

## Overview
VNC visual desktop streaming for sandbox environments. Captures the existing Xvfb virtual display via x11vnc and exposes it as a WebSocket stream via websockify for noVNC frontend consumption. Includes human takeover coordination to prevent human-machine conflicts.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | VNC visual desktop streaming — re-exports VncServer, TakeoverCoordinator, TakeoverLifecycleHook, TakeoverState, get_environment_hint. | ✅ |
| server.py | Core | VNC server lifecycle manager — lazy-start x11vnc + websockify on existing Xvfb display. Also provides `get_environment_hint()` for system prompt VNC awareness injection. | ✅ |
| takeover.py | Core | Takeover coordinator — state machine for human-agent browser control handoff. | ✅ |

## Architecture

```
Xvfb (already running for browser/computer_use toolkits)
  └─ x11vnc captures DISPLAY → RFB protocol on port 5900
      └─ websockify proxies RFB → WebSocket on port 6080
          └─ noVNC (frontend) connects via WebSocket

TakeoverCoordinator:
  AGENT_ACTIVE ──(user requests)──→ USER_TAKEOVER
       ↑                                  │
       └──(user resumes / timeout)────────┘

  Lifecycle hooks (async, Optional):
    on_takeover_start(reason) → business layer captures pre-state
    on_takeover_end(reason)   → business layer captures post-state
```

## Key Design Decisions

1. **Lazy loading**: VNC processes only start when frontend requests a connection. Zero cost when idle.
2. **Linux-only**: Requires X11 DISPLAY (Xvfb). macOS/Windows fall back to existing screenshot mode.
3. **Reuse existing Xvfb**: No new display server — captures the same DISPLAY used by browser and computer_use toolkits.
4. **Random one-time password**: x11vnc uses a fresh password per session, stored in a 0600-permission temp file to prevent other processes from reading it.
5. **Auto-revert timeout**: Takeover automatically returns control to Agent after 5 minutes (configurable).
6. **Environment awareness**: `get_environment_hint()` detects VNC availability and Xvfb resolution, returning a prompt string for system prompt injection. Process-level cached for deterministic output (KV-cache safe). Called by `platform.py`'s `environment_prompt_line`.
7. **Lifecycle hooks**: `on_takeover_start` / `on_takeover_end` are Optional async callbacks. Business layer registers them to capture page snapshots (ARIA tree) before/after human intervention, enabling skill evolution to learn from human demonstrations. Zero cost when unregistered.
8. **Health check with exponential backoff**: On VNC process crash, the health loop retries with exponential backoff (30s → 60s → 120s → 240s → 480s). After 5 consecutive failures it stops retrying and sets ERROR status, preventing log explosion when Xvfb is permanently unavailable.
