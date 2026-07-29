# persistence/

## Overview

SSOT for scanning text **before** it is written to durable stores (Memory, Wiki raw/publish, user-visible error text). Profiles tune strictness per surface; detection primitives live in `detection/`.

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Package | Re-exports scan API | — |
| `content_scan.py` | Core | `scan_persistable_content`, profiles `MEMORY_WRITE` / `WIKI_RAW` / `WIKI_PUBLISH`, `sanitize_display_secrets` | ✅ |

## Profiles

| Profile | Credential leaks | Prompt injection | Harmful state |
| --- | --- | --- | --- |
| `MEMORY_WRITE` | redact/block + optional PII pseudonymization | block ≥0.8 | block |
| `WIKI_RAW` | redact/block | **agent** caller block ≥0.8; settings/chat warn+log | — |
| `WIKI_PUBLISH` | redact/block | warn only | — |

## Key Dependencies

- `core.security.detection.*` (leak, prompt, harmful-state, content-boundary)

## Consumers

- `toolkits.memory.memory_scanner` — delegates Memory writes
- `toolkits.wiki.pipeline.raw_gate.security_hook` — raw + publish choke points
- `toolkits.wiki.resilience.sanitize` — display redaction
