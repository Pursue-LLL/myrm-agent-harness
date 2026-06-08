# fetchers/

## Overview
Toolkits Web_Fetch Fetchers module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| browser_fetcher.py | Core | Provides BrowserFetcher. | ✅ |
| http_fetcher.py | Core | L1 HTTP fetcher (Scrapling curl_cffi). HTTP/2 default; HTTP/3 retry on 403/antibot/empty only; skipped with proxy pool. | ✅ |
| protocols.py | Core | Provides FetcherType, FetchResult (with optional raw_body for binary), Fetcher protocol. | ✅ |
| stealth_fetcher.py | Core | Stealth Fetcher — Maximum anti-detection based on Scrapling Patchright + BrowserForge. DNS leak prevention via DoH when proxy is active. Ad/tracker domain blocking via Scrapling `block_ads`. | ✅ |
