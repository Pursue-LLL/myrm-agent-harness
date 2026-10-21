# optimization/

## Overview
Skill version history and skill content security validation. Framework-side protocols and types only; persistence is implemented by the host application.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill Optimization Toolkit | — |
| config.py | Config | `SecurityConfig`: dangerous-pattern list and sandbox-validation switch for skill content validation. | ✅ |
| protocols.py | Core | `SkillOptimizationStorage` (skill version CRUD, activation/rollback, retention, health) and `StorageError` (framework defines, server implements). | ✅ |
| security.py | Core | Multi-layer skill security validator (static scan, frontmatter, markdown; sandbox validation fails closed when enabled but unavailable). | ✅ |
| types.py | Config | `SkillVersion`, `SecurityValidationResult`, `SecurityError`. | ✅ |

## Key Dependencies

- `backends`
