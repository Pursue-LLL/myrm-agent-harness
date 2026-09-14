# browser/navigation/

## Overview

Page navigation utility — reusable across BrowserSession and BrowserFetcher. Provides `Navigator` (throttle + circuit breaker + smart wait + consent dismissal) and a Playwright document-level SSRF guard.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade: `Navigator` page navigation manager | ✅ |
| `ssrf_guard.py` | Core | `goto_with_ssrf_guard` — document-level route interception with redirect-chain validation (aligned with OpenClaw policy). Non-document routes and passed document routes fall through via `route.fallback()` so patchright's network-level init-script inject route still sees every document request (`continue_()` would terminate the handler chain and silently disable dom_enhancer / stealth / localStorage-restore init scripts). | ✅ |

## Key Dependencies

- `toolkits/browser/wait` — `wait_for_page_ready` + `WaitMetrics`
- `toolkits/browser/pool` — throttle/circuit-breaker/config
- `toolkits/browser/session.consent_dismisser` — cookie consent auto-dismiss
- `core/security` SSRF guards
