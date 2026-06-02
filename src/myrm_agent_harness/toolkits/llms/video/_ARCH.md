# video/

## Overview
Video generation module — multi-provider video generation with failover.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Video generation module — multi-provider video generation with failover. | — |
| _helpers.py | Internal | Used by generator.py for retry logic, error formatting, and content validation. | — |
| generator.py | Core | Video generation orchestrator. | ✅ |
| models.py | Core | Pure data types with no business logic. Mirrors the image module's | — |
| task_store.py | Core | Framework provides Protocol + two implementations (in-memory default, file-based). | — |
| video_engine.py | Core | Video generation tools for the agent. | ✅ |

| Submodule | Description |
|-----------|-------------|
| providers/ | Video generation providers — pluggable backends for video generation. |

## Key Dependencies

- `core`
