# fetchers/

## Overview
Toolkits Web_Fetch Fetchers module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| browser_fetcher.py | Core | Provides BrowserFetcher. A navigation the SSRF policy blocks raises `SSRFSecurityError` (never degrades to another tier); each fetch gets its own explicit-origin grants because pooled CRAWL contexts outlive it. | ✅ |
| http_fetcher.py | Core | L1 HTTP fetcher (Scrapling curl_cffi). HTTP/2 default; HTTP/3 retry on 403/antibot/empty only; skipped with proxy pool. SSRF defense through `FetchTargetGuard` on every redirect hop (DNS-pinning with TLS SAN fallback under the cloud policy); a rejected hop raises `SSRFSecurityError` instead of returning None, so the engine does not retry the same URL on a browser tier. | ✅ |
| target_guard.py | Core | `FetchTargetGuard` — per-fetch SSRF policy shared by the HTTP and stealth tiers. Cloud policy: DNS-resolved, every address public. Local policy (`allow_private_networks`): `RedirectHopEvaluator.evaluate_hop_resolved` (legacy numeric IPv4 spellings are canonicalised first; a hostname resolving to loopback, link-local or metadata is judged as that address), the requested origin may be private, any other private origin reached by redirect may not, cloud metadata never may; skill DLP allowlist and `MYRM_ALLOWED_INTERNAL_HOSTS` apply under both. | ✅ |
| protocols.py | Core | Provides FetcherType, FetchResult (with optional raw_body for binary), Fetcher protocol. | ✅ |
| stealth_fetcher.py | Core | Stealth Fetcher — Maximum anti-detection based on Scrapling Patchright + BrowserForge. DNS leak prevention via DoH when proxy is active. Ad/tracker domain blocking via Scrapling `block_ads`. Scrapling navigates without a route hook, so the requested URL is judged before the browser starts and the page it ended on before the body is returned (`SSRFSecurityError` otherwise); the hop between them cannot be vetted in flight. | ✅ |
