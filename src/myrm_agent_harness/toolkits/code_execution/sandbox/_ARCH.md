# sandbox/

## Overview
OS-level process sandbox for local/desktop execution.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | OS-level process sandbox for local/desktop execution. | — |
| detector.py | Core | Auto-detect the best available sandbox provider. | ✅ |
| policy_bridge.py | Core | Bridge between the permission engine's PathPolicy and OS-level SandboxPolicy. | ✅ |
| sandbox_types.py | Config | Foundation layer — all sandbox modules import from here. | ✅ |

| Submodule | Description |
|-----------|-------------|
| providers/ | Built-in sandbox providers. |
