# redirect_hop_guard/

## Overview

Redirect Private Address Hop Revalidation Suite. Private network and cloud metadata classification for browser navigations, the browser context filter and web_fetch redirect chains: the host as written, plus (local mode) the loopback, link-local or metadata address a hostname resolves to. It only judges a URL; enforcement (route aborts, tab resets, request refusal) lives with each caller.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Redirect Private Address Hop Revalidation Suite — re-exports the hop models, the evaluator and the explicit-origin grants. | ✅ |
| hop_evaluator.py | Core | Hop evaluation engine for redirect and subresource network security. `evaluate_hop` classifies the literal host as internal, cloud metadata (IMDS), loopback or link-local and assigns a disposition, without DNS. `evaluate_hop_resolved` is the local-mode entry point (grants given): it also looks a plain hostname up and judges loopback, link-local, unspecified and metadata answers (RFC 1918, CGNAT and benchmarking ranges are left alone because fake-IP proxies and VPNs hand them out for public names). Origins in the supplied grants relax the private-network rules; cloud metadata is never relaxed. | ✅ |
| name_resolution.py | Core | `resolve_addresses` — bounded (2 s), briefly cached (15 s, failures included) hostname lookup that never raises: an unresolvable or slow name reports no addresses, so a broken or proxy-only resolver cannot stop browsing. | ✅ |
| origin_grants.py | Core | Private-network origins a local-mode session was explicitly sent to — pure data (scheme, host, port), consumed by the evaluator. | ✅ |
| types.py | Core | Type definitions for the suite — hop disposition enum and per-hop evaluation result. | ✅ |
