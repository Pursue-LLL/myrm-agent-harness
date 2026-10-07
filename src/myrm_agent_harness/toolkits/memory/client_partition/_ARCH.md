# client_partition/

## Overview
Client-Isolated Workspace & Memory Namespace Partition Suite: memory scope level CLIENT derivation, zero-trust cross-client leakage firewall (CrossClientLeakGuard) screening retrieval candidates, and canonical containment workspace directory resolver (ClientWorkspaceResolver) preventing cross-client credential leaks and path traversal.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Entry point of the client partition subsystem in memory toolkit. | ✅ |
| `guard.py` | Core | Defensive screening engine enforcing strictly segregated boundaries between client accounts. | ✅ |
| `types.py` | Types | Data structures and value objects for client-isolated memory boundaries and workspace partitions. | ✅ |
| `workspace_resolver.py` | Core | Safe directory derivation and traversal prevention for client-isolated workspace partitions. | ✅ |

## Key Dependencies

- `toolkits.memory`
- External libraries: `pydantic`
