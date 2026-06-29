# core/security/http/

## Overview
SSRF-protected outbound HTTP primitives shared by harness toolkits, agent pipeline, and server media download.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports secure fetch API. | — |
| secure_fetch.py | Core | DNS-pinned HTTP with manual redirect loop (`secure_get`, `secure_request`, `resolve_secure_http_target`). | ✅ |

## Key Dependencies

- `core/security/guards/ssrf.py` — `async_pin_url`, `SSRFSecurityError`
- `httpx` — HTTP client

## Consumers

- `agent/context_management/pipeline/processors/media_resolver.py`
- `agent/skills/discovery/installers/zip_installer.py`
- `toolkits/openapi_bridge/spec_parser.py`, `http_executor.py`
- `toolkits/web_fetch/robots_parser.py`, `deep_crawl.py`
- `myrm-agent-server/app/channels/media/downloader.py`, `image_enrichment.py`
