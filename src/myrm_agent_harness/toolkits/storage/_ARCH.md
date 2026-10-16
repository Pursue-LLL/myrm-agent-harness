# storage/

## Overview
Storage abstraction layer.

Detailed design: [STORAGE_SYSTEM.md](STORAGE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Storage abstraction layer. | — |
| _fs_backend.py | Internal | File system storage backend base class. Centralizes aiofiles file operations and errno error handlin | ✅ |
| base.py | Core | Storage provider abstract base class. Defines the unified storage interface contract for all | ✅ |
| config.py | Config | Storage configuration module. The storage root is derived from MYRM_DATA_DIR with a ~/.myrm fallback | ✅ |
| factory.py | Core | Storage factory layer. Creates the local storage provider for a configuration and provides | ✅ |
| local.py | Core | Local file system storage backend. Stores files on local filesystem, suitable for development and | ✅ |

## Key Dependencies

- `infra`
