# captcha/

## Overview
CAPTCHA detection and coordination subsystem for browser automation. Provides Protocol-based pluggable solver architecture, HTML regex detector, asyncio.Event state machine coordinator, ManualSolver, and ApiSolver (CapSolver REST API).

Integrated into `BrowserSession.navigate()` and `BrowserSession.interact()` (click/dblclick only) — when a blocking CAPTCHA is detected, the coordinator pauses Agent execution and delegates to the configured solver.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for the CAPTCHA subsystem. | — |
| protocols.py | Core | Pure data types and protocol definitions: CaptchaType (10 variants), CaptchaStatus (state machine), CaptchaInfo, CaptchaSolveResult, CaptchaSolver Protocol. Zero runtime dependencies. | ✅ |
| detector.py | Core | Page-level blocking CAPTCHA detection via HTML regex. Two-tier patterns: Tier-1 (any page) and Tier-2 (short pages only). Reuses antibot_detector patterns + Cloudflare Turnstile. | ✅ |
| coordinator.py | Core | CAPTCHA coordination state machine. Manages DETECTED → SOLVING → RESOLVED/TIMEOUT transitions. Uses asyncio.wait_for for timeout enforcement. Publishes captcha_detected/resolved/timeout events and dispatches browser_takeover_requested/completed (with auto_detect_completion, is_managed) for frontend takeover UI sync. | ✅ |
| manual_solver.py | Core | Default human-in-the-loop solver. Polls page via detect_captcha to detect CAPTCHA disappearance after user manually solves it. Works across Local/Tauri/SaaS deployments. | ✅ |
| api_solver.py | Core | Automatic CAPTCHA solver via CapSolver REST API. Supports reCAPTCHA v2/v3, hCaptcha, Cloudflare Turnstile/Challenge. Extracts websiteKey from page HTML, calls createTask/getTaskResult, injects token. | ✅ |
| fallback_solver.py | Core | Chain-of-responsibility solver. Tries primary (ApiSolver) first, falls back to secondary (ManualSolver) on failure. Stateless, ~40 lines. | ✅ |

## Solver Selection (business layer)

The `myrm-agent-server/tool_setup.py` dynamically selects the solver at session creation:
- **With CapSolver API key configured**: `FallbackSolver(ApiSolver(key), ManualSolver())`
- **Without configuration**: `ManualSolver()` (preserves existing behavior)

Configuration is stored in `UserConfig` (key: `captchaSolverConfig`, encrypted).

## Key Dependencies

- `agent.streaming.types` (AgentEventType — CAPTCHA event types)
- `utils.event_utils` (dispatch_custom_event — event publishing)
- `patchright.async_api` (Page — browser page interface, TYPE_CHECKING only)
- `httpx` (ApiSolver — async HTTP client for CapSolver API)
