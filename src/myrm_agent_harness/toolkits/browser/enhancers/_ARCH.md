# enhancers/

## Overview
DOM enhancers for the browser toolkit. Injects JavaScript to improve page readability and accessibility.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports `get_dom_enhancer_script` and `install_document_script_injection`. | — |
| `dom_enhancer_loader.py` | Core | Loads and caches DOM enhancement JavaScript for injection into browser pages. | ✅ |
| `inject_route.py` | Core | `install_document_script_injection` — per-context document-response rewrite (`route.fulfill`) that prepends `<script>` tags to every HTML page; the reliable script-delivery path under patchright where `add_init_script` silently no-ops. One route handler serves ALL registered scripts (fulfill terminates the route chain, so multiple handlers would be mutually exclusive). The handler is transparent to everything it does not rewrite: it fetches with `max_redirects=0` and hands 3xx, non-HTML, empty and undecodable responses back to Chromium unchanged via `route.fulfill(response=…)`, so Chromium performs the redirect itself (correct page URL and origin, cookies, `redirected_from` chain visible to the SSRF checks) and no document is requested twice; script sources are escaped against `</script>` breakouts; charset-aware decode/encode keeps legacy-charset pages intact; undecodable bodies fall through untouched (known limitation: pages with strict CSP blocking inline scripts get no enhancement — the only CSP-proof channel, CDP `addScriptToEvaluateOnNewDocument`, is broken in patchright). | ✅ |

## Key Dependencies

- patchright.async_api (BrowserContext, Route)
- pool.stealth (stealth.js consumer of inject_route)