# sandbox/

## Overview
OS-level process sandbox for local/desktop execution.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | OS-level process sandbox for local/desktop execution. | — |
| detector.py | Core | Auto-detect the best available sandbox provider. | ✅ |
| mount_security_gate.py | Core | Fail-closed security gate for sandbox mounts (path traversal, symlink escape, device blocking). | ✅ |
| privacy_ladder.py | Core | Three-tier fail-closed privacy ladder for sandbox persistence and snapshot validation. | ✅ |
| policy_bridge.py | Core | Bridge between the permission engine's PathPolicy and OS-level SandboxPolicy. | ✅ |
| sandbox_types.py | Config | Foundation layer — all sandbox modules import from here. | ✅ |

| Submodule | Description |
|-----------|-------------|
| providers/ | Built-in sandbox providers. |
