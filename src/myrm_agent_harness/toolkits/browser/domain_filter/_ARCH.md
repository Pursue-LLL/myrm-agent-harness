# browser/domain_filter/

## Overview

Deep domain filtering — four-layer defense-in-depth for browser network egress (CSP + protocol interception + main-thread hardening + CDP audit), plus ad/tracker domain blocking.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade: `DomainAllowlist`, `install_domain_filter` (four-layer installer with resource blocking; forwards `allow_private_networks` to the Layer 1 filter). `DomainAllowlist` matches exact and `*.` wildcard patterns; callers use `is_allowed` (allowlist semantics) or `is_blocked` (blocklist semantics) on the same matching core. | ✅ |
| `ad_domains.py` | Data | Lazily-loaded frozenset of ~3500 ad/tracker domains (bundled `assets/ad_domains.txt`) | ✅ |
| `http_filter.py` | Core | Layer 1 route filter: hop-by-hop private network / cloud-metadata revalidation (empty hostname fails closed). Cloud mode checks every request type; local mode (`allow_private_networks`) checks only documents, against the session's explicit-origin grants (cloud metadata is never relaxed), because subresources of a local page are left to Chromium's private-network-access rules. Every later rule still applies, ad/tracker blocklist, domain block/allow lists, resource-type blocking; document hops that violate policy are aborted and the tab reset to `about:blank`. Only requests routed to the filter are judged: patchright does not route the hops of a document redirect, so the domain lists see the entry URL and subresources but not a redirect target (private and metadata targets are judged after the load by `navigation/ssrf_guard.py`). | ✅ |

## Key Dependencies

- `toolkits/browser/pool.config` — `ResourceBlockConfig`
- `toolkits/browser/assets/ad_domains.txt` — bundled blocklist data
