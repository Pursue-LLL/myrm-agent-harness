# pipeline/resilience/

## Overview

Wiki compile failure policy, circuit pause/resume state, and user-safe error display.
Consumed by `queue.py` and `compiler.py`; exposed to product UI via server `compile_run` DTO.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports | — |
| `types.py` | Core | `CompileRunSnapshot` (incl. compile phase + survey stats), `FailureResolution` | ✅ |
| `failure_policy.py` | Core | ErrorKind SSOT mapping, batch pause rules, transient detection | ✅ |
| `circuit.py` | Core | SQLite `compile_circuit` store (running/paused, compile phase + survey stats) | ✅ |
| `sanitize.py` | Core | Redact API keys from queue error messages | ✅ |

## v1 Scope

- Pause on any auth/billing failure in a zero-success batch, transient clusters, or 5+ failures.
- `compile_all()` and worker loop both respect `is_compile_paused()` (no LLM drain while paused).
- Transient-only automatic retry with fixed backoff seconds.
- No HALF_OPEN auto-probe (explicit user resume / retry-all recovery).

## Dependencies

- `toolkits.llms.errors.classifier` (ErrorKind SSOT)
- `utils.db.sqlite` (hardened SQLite connections)
