# sovereign_migration/

## Overview
Sovereign Asset Package Cross-Machine Migration Protocol & One-Click Restore: portable bundle packaging (.myrmpkg), checksum verification, dynamic path relativization, atomic restoring, and competitor ingestion adapters (Hermes, Claude Code, Codex).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Sovereign digital asset package migration and cross-machine restore toolkit. | ✅ |
| `bundle_archiver.py` | Core | Consistent atomic packaging and checksum-verified sovereign asset archiver. | ✅ |
| `bundle_restorer.py` | Core | Atomic unpacker, integrity validator, and path-remapping restorer for sovereign asset bundles. | ✅ |
| `competitor_adapter.py` | Core | Universal competitor ingestion and translation adapter (Hermes, Claude Code, Codex). | ✅ |
| `path_relativizer.py` | Core | Dynamic path relativization and cross-machine absolute path remapping engine. | ✅ |
| `types.py` | Types | Type definitions for sovereign asset bundle migration and cross-machine restore protocol. | ✅ |

## Key Dependencies

- External libraries: `pydantic`
