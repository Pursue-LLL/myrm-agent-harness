# persistence/

## Overview

SSOT for scanning text **before** it is written to durable stores (Memory, Wiki raw/publish, user-visible error text). Profiles tune strictness per surface; detection primitives live in `detection/`.

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Package | Re-exports scan API | — |
| `content_scan.py` | Core | `scan_persistable_content` (`pseudonymize=False` for verdict-only probes), profiles `MEMORY_WRITE` / `WIKI_RAW` / `WIKI_PUBLISH`, `sanitize_display_secrets`, context-local PII pseudonymizer (ContextVar, inherited by fire-and-forget task snapshots) | ✅ |
| `secret_spans.py` | Core | `find_assignment_secret_spans` (values assigned to password/api_key/secret/token-style keys, located through `assignment_sweep.find_assignment_matches`; quoted values extend to the closing quote, unquoted values stop at the first non-ASCII character) and `redact_spans` (position-based replacement; overlapping spans collapse into one marker) | ✅ |

## Profiles

| Profile | Credential leaks | Prompt injection | Instruction shape | Harmful state |
| --- | --- | --- | --- | --- |
| `MEMORY_WRITE` | redact/block + optional PII pseudonymization | block ≥0.8 | warn | block |
| `WIKI_RAW` | redact/block | **agent** caller block ≥0.8; settings/chat warn+log | warn | — |
| `WIKI_PUBLISH` | redact/block | warn only | warn | — |

Instruction-shape detection (guardrail bypass / unattended execution / exfiltration / spoofed approval / agent command) always results in WARN — it never blocks, because a human may legitimately hold such preferences. Secrets anchored to a credential keyword (`password is X`, `密码：X`, `PIN is 482913`, generated-looking token next to the keyword) and values assigned to sensitive keys (`password=x`, `"api_key": "x"`) are redacted by span alongside structured credential patterns; a keyword elsewhere in a long text never turns ordinary words into secrets, and redacted text scans clean (idempotent).

## Key Dependencies

- `core.security.detection.*` (leak + password-like, prompt, instruction-shape, harmful-state, content-boundary)
- `core.security.assignment_sweep` (`find_assignment_matches`: the single definition of a non-benign secret assignment, with the value span)

## Consumers

- `toolkits.memory._internal.memory_scanner` — delegates Memory writes
- `toolkits.wiki.pipeline.raw_gate.security_hook` — raw + publish choke points
- `toolkits.wiki.resilience.sanitize` — display redaction
