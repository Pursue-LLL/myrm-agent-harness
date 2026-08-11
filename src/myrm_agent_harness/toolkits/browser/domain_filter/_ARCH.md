# browser/domain_filter/

## Overview

Deep domain filtering — four-layer defense-in-depth for browser network egress (CSP + protocol interception + main-thread hardening + CDP audit), plus ad/tracker domain blocking.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade: `DomainAllowlist`, `install_domain_filter` (four-layer installer with resource blocking) | ✅ |
| `ad_domains.py` | Data | Lazily-loaded frozenset of ~3500 ad/tracker domains (bundled `assets/ad_domains.txt`) | ✅ |

## Key Dependencies

- `toolkits/browser/pool.config` — `ResourceBlockConfig`
- `toolkits/browser/assets/ad_domains.txt` — bundled blocklist data
