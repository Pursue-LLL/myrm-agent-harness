# core/

## Overview
Shared runtime infrastructure for the ACP toolkit — cross-cutting mechanisms consumed by the runtime and server subsystems.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package marker with module overview; no public re-exports. | — |
| backend_detector.py | Core | Automatic detection of CLI agent backends (process-level dual cache + soft TTL + optional `refresh` bypass). | ✅ |
| event_bus.py | Core | ACP event bus layer. Provides decoupled event dispatch mechanism for the Runtime system with session | ✅ |
| health_monitor.py | Core | Health monitor for RuntimeBackend instances. | ✅ |
| permission.py | Core | ACP permission management layer. Provides framework-level permission control with safe/ask/allow_all | ✅ |

## Module Dependencies

- `toolkits/acp/types.py` — runtime type definitions (contract layer)
- `toolkits/acp/auth/` — backend detector only (TYPE_CHECKING)
- `toolkits/acp/toolchains/` — backend detector only (toolchain base dir)
