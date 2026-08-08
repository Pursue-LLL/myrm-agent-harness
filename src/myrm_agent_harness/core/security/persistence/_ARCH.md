# persistence/

## Overview

SSOT for scanning text **before** it is written to durable stores (Memory, Wiki raw/publish, user-visible error text). Profiles tune strictness per surface; detection primitives live in `detection/`.

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Package | Re-exports scan API | — |
| `content_scan.py` | Core | `scan_persistable_content`, profiles `MEMORY_WRITE` / `WIKI_RAW` / `WIKI_PUBLISH`, `sanitize_display_secrets` | ✅ |

## Profiles

| Profile | Credential leaks | Prompt injection | Instruction shape | Harmful state |
| --- | --- | --- | --- | --- |
| `MEMORY_WRITE` | redact/block + optional PII pseudonymization | block ≥0.8 | warn | block |
| `WIKI_RAW` | redact/block | **agent** caller block ≥0.8; settings/chat warn+log | warn | — |
| `WIKI_PUBLISH` | redact/block | warn only | warn | — |

Instruction-shape detection (guardrail bypass / unattended execution / exfiltration / spoofed approval / agent command) always results in WARN — it never blocks, because a human may legitimately hold such preferences. Password-like tokens (keyword + mixed-char heuristic) are redacted alongside structured credential patterns.

## Key Dependencies

- `core.security.detection.*` (leak + password-like, prompt, instruction-shape, harmful-state, content-boundary)

## Consumers

- `toolkits.memory._internal.memory_scanner` — delegates Memory writes
- `toolkits.wiki.pipeline.raw_gate.security_hook` — raw + publish choke points
- `toolkits.wiki.resilience.sanitize` — display redaction
