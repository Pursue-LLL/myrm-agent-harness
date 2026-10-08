# unload_guard/

## Overview
Desktop & WebUI Unload Graceful Flush Finalize Guard: zero-LLM crash-proof emergency snapshotting upon browser unload or window close, sub-millisecond markdown memorandum persistence, and startup restoration.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public entry point for desktop/WebUI unload and graceful flush finalize guard. | ✅ |
| `guard.py` | Core | Atomic emergency graceful flush guard and session recovery manager. | ✅ |
| `snapshot_builder.py` | Core | Zero-LLM emergency snapshot generator for graceful unload and crash fallback. | ✅ |
| `types.py` | Types | Type definitions for desktop/WebUI unload and graceful flush finalize guard. | ✅ |

## Key Dependencies

- `toolkits.memory.handoff`
- External libraries: `pydantic`
