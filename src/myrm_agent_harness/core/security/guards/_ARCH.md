# core/security/guards/

## Overview
Session-level security guards — privacy tracking, SSRF prevention, and skill DLP domain allowlist.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module docstring. | — |
| privacy_tracker.py | Core | Privacy tracker — per-turn PII sensitivity tracking, ContextVar-based privacy policy access (set/get_privacy_policy). | ✅ |
| ssrf.py | Core | Unified outbound URL SSRF validation — sync/async validate, DNS-pinned URLs, SSRF_BLOCKED audit on block. HTTP fetch: `core/security/http/secure_fetch.py`. | ✅ |
| url_allowlist.py | Core | ContextVar-based skill `allowed-domains` DLP guard for outbound HTTP. | ✅ |

## Key Dependencies

- `utils/url_utils.py` — `is_blocked_ip`, `validate_scheme_and_hostname` (primitives only)
- `core/security/audit.py` — `record_decision` for SSRF_BLOCKED entries
- No `agent/` imports (toolkits gate)
