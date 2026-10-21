# sandbox/

## Overview
OS-level process sandbox for local/desktop execution. `SandboxPolicy.writable_paths` is the complete writable set besides the provider's scratch areas (such as `/tmp`): no provider grants the working directory implicitly, so an empty `writable_paths` yields a read-only workspace.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | OS-level process sandbox for local/desktop execution. | — |
| detector.py | Core | Auto-detect the best available sandbox provider. | ✅ |
| mount_security_gate.py | Core | Fail-closed dual-direction security gate for sandbox mounts (source & target traversal, UNC/SMB hash defense, container system root overwrite protection, symlink escape, device blocking, collision resolver). | ✅ |
| privacy_ladder.py | Core | Three-tier fail-closed privacy ladder for sandbox persistence and snapshot validation. | ✅ |
| policy_bridge.py | Core | Bridge between the permission engine's PathPolicy and OS-level SandboxPolicy. | ✅ |
| sandbox_types.py | Config | Foundation layer — all sandbox modules import from here. | ✅ |

| Submodule | Description |
|-----------|-------------|
| providers/ | Built-in sandbox providers. |
