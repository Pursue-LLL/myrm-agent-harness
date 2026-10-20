# hot_handoff/

## Overview
Local-to-cloud task hot handoff and input consistency verification suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Local-to-cloud task hot handoff and input consistency verification suite. | — |
| `handoff_types.py` | Core | Strongly typed data contracts for local-to-cloud task hot handoff and input integrity verification. | ✅ |
| `hot_handoff_coordinator.py` | Core | Local-to-cloud hot handoff coordinator and two-way task relay pipeline. | ✅ |
| `material_integrity_guard.py` | Core | Streaming cryptographic material integrity guard and input hash verifier. | ✅ |
| `workspace_syncer.py` | Core | Workspace incremental delta synchronization and archive bundle manager. | ✅ |
