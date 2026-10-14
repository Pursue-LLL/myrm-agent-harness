# browser/navigation/

## Overview

Page navigation utility — reusable across BrowserSession and BrowserFetcher. Provides `Navigator` (throttle + circuit breaker + smart wait + consent dismissal) and a Playwright document-level SSRF guard.

A navigation that outlives its budget is settled: the load is stopped over CDP, then the document counts as committed only if the page URL changed. A committed document is returned as partial content (HTTP 200 assumed); otherwise the call fails with `BrowserNavigationError`, and a page that no longer answers raises `PageUnresponsiveError` so the session can heal the tab.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade: `Navigator` page navigation manager. In local mode (`allow_private_networks`) it hands the guard the grants of the page's context, or a private set passed as `private_origins` (BrowserFetcher: grants must not outlive one pooled-page use). | ✅ |
| `ssrf_guard.py` | Core | `goto_with_ssrf_guard` — document-level route interception plus post-load redirect-chain validation (`request.redirected_from`; patchright does not route redirect hops). Cloud policy: DNS-resolved `async_pin_url`. Local policy (grants given): literal-host classification, a private origin is reachable only where the agent navigated explicitly, cloud metadata never; the requested URL is checked before `page.goto` because aborting a main-frame navigation in the route commits Chromium's error page and loses the previous one, and a blocked chain resets the tab to `about:blank`. A goto that fails because the route aborted it is re-raised as `BrowserNavigationBlockedError`. Non-document routes and passed document routes fall through via `route.fallback()` (not `continue_()`) so subsequent route handlers on the same context still run. A failed or cancelled navigation is aborted at the protocol level (`abort_pending_navigation`) and the route teardown is time-bounded, because `unroute` never answers on a page stuck in a stalled navigation. | ✅ |

## Key Dependencies

- `toolkits/browser/wait` — `wait_for_page_ready` + `WaitMetrics`
- `toolkits/browser/pool` — throttle/circuit-breaker/config
- `toolkits/browser/session.consent_dismisser` — cookie consent auto-dismiss
- `core/security` SSRF guards and `redirect_hop_guard` (`RedirectHopEvaluator`, `PrivateOriginGrants`)
- `toolkits/browser/utils.private_origins` — per-context grants registry
