# pipeline/resilience/

## Overview

Wiki compile failure policy, circuit pause/resume state, and user-safe error display.
Consumed by `queue.py` and `compiler.py`; exposed to product UI via server `compile_run` DTO.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports | ✅ |
| `types.py` | Core | `CompileRunSnapshot` (incl. compile phase + survey stats), `FailureResolution` (the error kind a queue row is failed with and the retry backoff) | ✅ |
| `failure_policy.py` | Core | ErrorKind SSOT mapping, the transient set the queue's retry selection shares, batch pause rules, embed window violation, `resolve_blocked_publish` (an article the publish content scan refused is a permanent `safety_block`), `reraise_if_cancelled` (raise a `CancelledError` again when the running task really was asked to stop, so a stop is not swallowed on the way out) | ✅ |
| `circuit.py` | Core | SQLite `compile_circuit` store (running/paused, compile phase + survey stats) | ✅ |
| `sanitize.py` | Core | Redact API keys from queue error messages | ✅ |

## v1 Scope

- Pause on any auth/billing failure in a zero-success batch, transient clusters, or 5+ failures; the rule is applied to the extraction step and again to the article step of a batch (success there is a written or staged article).
- Pause immediately on embed window violations during article publish/index upsert.
- `compile_all()` and worker loop both respect `is_compile_paused()` (no LLM drain while paused).
- Transient-only automatic retry with fixed backoff seconds.
- No HALF_OPEN auto-probe (explicit user resume / retry-all recovery).

## Dependencies

- `toolkits.llms.errors.classifier` (ErrorKind SSOT)
- `utils.db.sqlite` (hardened SQLite connections)
