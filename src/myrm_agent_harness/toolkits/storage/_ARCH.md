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
| cached.py | Core | Performance-optimization decorator for any StorageProvider backend. | ✅ |
| config.py | Config | Storage configuration module. All configs injected via constructor parameters with sensible defaults | ✅ |
| factory.py | Core | Storage factory layer. Creates storage provider instances based on configuration and provides | ✅ |
| local.py | Core | Local file system storage backend. Stores files on local filesystem, suitable for development and | ✅ |
| paths.py | Core | Storage path utility module. Centrally manages storage system path generation, ensuring all | ✅ |
| persistent.py | Core | Container persistent storage backend. Intelligently routes to /persistent or /workspace by path pref | ✅ |
| types.py | Config | Storage layer type definitions. Defines base types and enums related to storage paths (path conventi | ✅ |

## Key Dependencies

- `infra`
