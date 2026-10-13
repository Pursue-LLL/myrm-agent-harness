# utils/

## Overview
Shared utilities and constants for the browser toolkit.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports utility components. | ✅ |
| selectors.py | Core | Shared CSS selectors (e.g., PASSWORD_FIELD_SELECTOR). | ✅ |
| proxy_error.py | Core | Proxy and network error pattern detection for browser navigation diagnostics | ✅ |
| timeout.py | Core | Timeout detection helper: recognizes both builtin and patchright `TimeoutError` (which do not share a base class). | ✅ |
| page_health.py | Core | Bounded browser and page health primitives: `abort_pending_navigation` (CDP `Page.stopLoading` first, `window.stop()` fallback), `probe_alive` (page) and `probe_browser_alive` (browser process, `Browser.getVersion`), `close_page_bounded` / `detach_cdp_bounded` (teardown), `PageUnresponsiveError`. Every call carries its own bound because page-level commands hang without one on a stalled or spinning page. | ✅ |
