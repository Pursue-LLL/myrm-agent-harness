# history/

## Overview
Skills History module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| jsonl_backend.py | Core | Implements SkillHistoryBackend using JSONL files for history storage. | ✅ |
| protocols.py | Core | Protocol for skill history storage. Allows different storage backends | ✅ |
| tracking_backend.py | Core | Framework-layer wrapper that adds history tracking to skill write operations. | ✅ |
| types.py | Config | Data structures for skill modification history tracking. | ✅ |

## Key Dependencies

- `agent`
- `backends`
