# core/security/http/

## Overview
SSRF-protected outbound HTTP primitives shared by harness toolkits, agent pipeline, and server media download.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports secure fetch and redirect guard APIs. | — |
| redirect_guard.py | Core | Outbound HTTP redirect sensitive header protection. `extract_origin` (default port 80/443 normalization), `is_same_origin`, `is_sensitive_header` (standard RFC keys + wildcard regex), `strip_sensitive_headers_on_redirect` (purges credentials on cross-origin redirect and blocks HTTPS->HTTP downgrade), and `create_mcp_redirect_guard_event_hooks` (httpx/httpx2 client hooks for MCP transports). | ✅ |
| secure_fetch.py | Core | DNS-pinned HTTP with manual redirect loop (`secure_get`, `secure_request`, `resolve_secure_http_target`) and integrated cross-origin sensitive header stripping (`strip_sensitive_headers_on_redirect`). `secure_get`/`secure_request` accept `max_content_length` to abort oversized bodies mid-stream (`ContentTooLargeError`); defaults to `DEFAULT_MAX_CONTENT_LENGTH` (20 MB) unless `None` is passed to disable. | ✅ |

## Key Dependencies

- `core/security/guards/ssrf.py` — `async_pin_url`, `SSRFSecurityError`
- `httpx` — HTTP client

## Consumers

- `agent/context_management/pipeline/processors/media_resolver.py`
- `agent/skills/market/installers/zip_installer.py`
- `agent/skills/market/helpers.py`
- `agent/hooks/executor.py`
- `toolkits/a2a/resolver.py`
- `toolkits/cron/delivery.py`
- `toolkits/openapi_bridge/spec_parser.py`, `http_executor.py`
- `toolkits/wiki/wiki_agent_tools.py` (`_fetch_url_as_markdown`)
- `toolkits/wiki/pipeline/ingress/asset_store.py`
- `toolkits/llms/image/generator.py`, `models.py` (reference/result URL downloads)
- `toolkits/llms/video/video_engine.py` (`_resolve_media_sources` HTTP branch)
- `toolkits/llms/video/providers/google_provider.py`, `minimax_provider.py`, `qwen_provider.py` (API result download URLs)
- `myrm-agent-server/app/ai_agents/media_tools/image_agent_tool.py`
- `myrm-agent-server/app/channels/media/image_enrichment.py`
- `myrm-agent-server/app/channels/providers/feishu/sdk/client.py` (`download_url`)
- `myrm-agent-server/app/api/integrations/llms.py` (model discovery)
- `myrm-agent-server/app/services/kanban/kanban_attach_handler.py`

Browser Playwright navigation uses `toolkits/browser/navigation/ssrf_guard.py` (`async_pin_url`, not httpx).
`http_fetcher.py` uses per-hop `async_pin_url` via scrapling with validated domain fallback on TLS SAN mismatch (security-equivalent).
