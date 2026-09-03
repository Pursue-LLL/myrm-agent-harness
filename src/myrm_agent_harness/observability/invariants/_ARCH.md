# observability/invariants/

## Overview

Package-owned runtime invariant assertions and registry service. Validates cross-event causality, state machine transition validity, and data integrity with zero production overhead (No-Op support) and strict development fail-fast mode.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports RuntimeInvariantRegistry, InvariantViolation, InvariantError, and core checks. | ✅ |
| `types.py` | Core | Foundation type system: InvariantSeverity (ERROR, WARN), InvariantViolation, InvariantCheckerProtocol. | ✅ |
| `bootstrap.py` | Core | One-time runtime invariant registry bootstrap (`ensure_runtime_invariants_installed`). | ✅ |
| `config.py` | Config | Runtime invariant mode configuration from environment (`get_invariant_mode`). | ✅ |
| `registry.py` | Core | RuntimeInvariantRegistry service with mode switching (STRICT, WARN, DISABLED) and regex filtering. | ✅ |
| `core_pack.py` | Core | Standard core invariant companion checks (event pairing, lifecycle state transitions, Todo structure, Step enclosure, Sequence continuity). | ✅ |

## Key Dependencies

- `observability/diagnostics` (optional linkage for invariant finding surfacing)
