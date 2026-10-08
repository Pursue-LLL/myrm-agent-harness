# core/security/dir_trust_gate/

## Overview
Directory trust gate primitives for preventing credential exfiltration in untrusted cloned repositories.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for DirectoryTrustStore, DirTrustGate, and types. | — |
| `types.py` | Types | Domain models for project remote configuration and trust evaluations. | ✅ |
| `trust_store.py` | Storage | Canonical path normalization and persistent store for trusted directories. | ✅ |
| `gate.py` | Core | Trust evaluation logic dropping remote credentials in untrusted directories. | ✅ |

## Dependencies
- Standard library: `json`, `os`, `pathlib`, `threading`, `time`
- No internal harness coupling.
