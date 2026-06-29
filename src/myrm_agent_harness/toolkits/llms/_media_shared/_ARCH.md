# _media_shared/

## Overview
Shared across video/ and image/ modules. Keeps media-specific logic

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Shared across video/ and image/ modules. Keeps media-specific logic | — |
| normalization.py | Core | Used by video/generator.py and future image/generator.py to normalize | ✅ |
| security.py | Core | Delegates SSRF logic to `core.security.guards.ssrf` (single source of truth). | ✅ |
| task_store.py | Core | Generic store shared by video/ and image/ modules. Framework provides | — |
| types.py | Config | These types are imported by video/models.py, normalization.py, and task_store.py. | — |

## Key Dependencies

- `core`
