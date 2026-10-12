# workspace_path_rbac/

## Overview

Granular Workspace Path RBAC & Denial Audit Suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Granular Workspace Path RBAC & Denial Audit Suite | ✅ |
| audit_ledger.py | Core | Structured Filesystem Audit Ledger tracking all workspace operations and denials — Tamper-evident ledger providing enterprise file governance transparency. | ✅ |
| guard.py | Core | Composite Guard orchestrating Workspace Path RBAC and Audit Ledger — Main architectural boundary for workspace path segregation and triple write defense. | ✅ |
| policy_engine.py | Core | Policy evaluation engine for Granular Workspace Path RBAC — Filesystem RBAC evaluation barrier enforcing read/write path segregation. | ✅ |
| types.py | Core | Core data structures and types for Workspace Path RBAC & Denial Audit — Harness core security contracts for granular filesystem isolation and write protection. | ✅ |
