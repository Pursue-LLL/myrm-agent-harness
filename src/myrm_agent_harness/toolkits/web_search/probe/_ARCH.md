# probe/

## Overview
Local and self-hosted search service discovery (SearXNG ping + HTML verify).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports probe helpers and SearXNG constants | ✅ |
| constants.py | Core | Canonical SearXNG URLs and region presets | ✅ |
| local_probe.py | Core | HTTP probes for SearXNG endpoints during onboarding/setup | ✅ |

## Dependencies

- `infra.tls_compat`
