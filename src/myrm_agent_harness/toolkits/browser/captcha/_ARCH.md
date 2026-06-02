# captcha/

## Overview
CAPTCHA detection and coordination subsystem for browser automation. Provides Protocol-based pluggable solver architecture, HTML regex detector, asyncio.Event state machine coordinator, and default ManualSolver.

Integrated into `BrowserSession.navigate()` and `BrowserSession.interact()` (click/dblclick only) — when a blocking CAPTCHA is detected, the coordinator pauses Agent execution and delegates to the configured solver.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for the CAPTCHA subsystem. | — |
| protocols.py | Core | Pure data types and protocol definitions: CaptchaType (10 variants), CaptchaStatus (state machine), CaptchaInfo, CaptchaSolveResult, CaptchaSolver Protocol. Zero runtime dependencies. | ✅ |
| detector.py | Core | Page-level blocking CAPTCHA detection via HTML regex. Two-tier patterns: Tier-1 (any page) and Tier-2 (short pages only). Reuses antibot_detector patterns + Cloudflare Turnstile. | ✅ |
| coordinator.py | Core | CAPTCHA coordination state machine. Manages DETECTED → SOLVING → RESOLVED/TIMEOUT transitions. Uses asyncio.wait_for for timeout enforcement. Publishes events via dispatch_custom_event. | ✅ |
| manual_solver.py | Core | Default human-in-the-loop solver. Polls page via detect_captcha to detect CAPTCHA disappearance after user manually solves it. Works across Local/Tauri/SaaS deployments. | ✅ |

## Key Dependencies

- `agent.streaming.types` (AgentEventType — CAPTCHA event types)
- `utils.event_utils` (dispatch_custom_event — event publishing)
- `patchright.async_api` (Page — browser page interface, TYPE_CHECKING only)
