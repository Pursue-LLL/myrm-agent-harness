# core/security/admin_auth_surface/

## Overview
Unified authentication surface governance and anti-lockout invariant validation engine.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for manager, validator, and configuration types. | — |
| `types.py` | Types | Domain models for login methods, OAuth connections, and validation results. | ✅ |
| `validator.py` | Core | Anti-lockout invariant evaluation and secret masking helpers. | ✅ |
| `manager.py` | Core | Lifecycle manager enforcing safe configuration updates and secret preservation. | ✅ |

## Dependencies
- Standard library: `collections.abc`, `dataclasses`, `enum`
- No internal harness coupling.
