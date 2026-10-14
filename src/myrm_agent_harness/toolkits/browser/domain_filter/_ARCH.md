# browser/domain_filter/

## Overview

Deep domain filtering — four-layer defense-in-depth for browser network egress (CSP + protocol interception + main-thread hardening + CDP audit), plus ad/tracker domain blocking.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade: `DomainAllowlist`, `install_domain_filter` (four-layer installer with resource blocking; forwards `allow_private_networks` to the Layer 1 filter). `DomainAllowlist` matches exact and `*.` wildcard patterns; callers use `is_allowed` (allowlist semantics) or `is_blocked` (blocklist semantics) on the same matching core. | ✅ |
| `ad_domains.py` | Data | Lazily-loaded frozenset of ~3500 ad/tracker domains (bundled `assets/ad_domains.txt`) | ✅ |
| `context_lists.py` | Core | `DomainListPolicy` (blocklist first, then allowlist; empty lists impose nothing; a missing hostname fails closed under an allowlist) plus the per-context registry `bind_domain_lists` / `domain_lists_for` (weak-keyed by `BrowserContext`, like `utils.private_origins`). One rule, two consumers: the Layer 1 request filter and the navigation guard's redirect-hop check, so a hostname gets the same verdict whichever way it was reached. | ✅ |
| `http_filter.py` | Core | Layer 1 route filter: hop-by-hop private network / cloud-metadata revalidation (empty hostname fails closed). Cloud mode checks every request type; local mode (`allow_private_networks`) checks only documents, against the session's explicit-origin grants (cloud metadata is never relaxed; a hostname resolving to loopback, link-local or metadata counts as that address), because subresources of a local page are left to Chromium's private-network-access rules. Every later rule still applies, ad/tracker blocklist, domain block/allow lists, resource-type blocking; document hops that violate policy are aborted and the tab reset to `about:blank`. Only requests routed to the filter are judged: patchright does not route the hops of a document redirect, so the filter sees the entry URL and subresources but not a redirect target. It binds its `DomainListPolicy` to the context, and `navigation/ssrf_guard.py` replays the redirect chain after the load, judging private and metadata targets by address and every hop after the entry URL against the same domain lists. | ✅ |

## Key Dependencies

- `toolkits/browser/pool.config` — `ResourceBlockConfig`
- `toolkits/browser/assets/ad_domains.txt` — bundled blocklist data
