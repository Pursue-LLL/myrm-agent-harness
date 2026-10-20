# sovereign_migration/

## Overview
Third-party assistant asset detection and ingestion (Hermes, Claude Code, Codex). Whole-instance backup and cross-device restore live in `infra/state_archive` (generic primitive) and the server's `instance_archive` (policy), not here.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Third-party assistant asset detection and ingestion toolkit. | ✅ |
| `competitor_adapter.py` | Core | Universal competitor ingestion and translation adapter (Hermes, Claude Code, Codex). | ✅ |
| `tool.py` | Agent Tool | Agent-facing LangChain tool for competitor asset detection and ingestion. | ✅ |
| `types.py` | Types | Type definitions for competitor asset detection and ingestion. | ✅ |
| `bundle_archiver.py` | Core | Consistent atomic packaging and checksum-verified sovereign asset archiver. — SovereignBundleArchiver: Produces atomic verified sovereign asset bundles (.myrmpkg) for migration.; time_tag: Format short human timestamp for package identifier. | ✅ |
| `bundle_restorer.py` | Core | Atomic unpacker, integrity validator, and path-remapping restorer for sovereign asset bundles. — SovereignBundleRestorer: Restores sovereign asset packages with checksum integrity and path remapping. | ✅ |
| `path_relativizer.py` | Core | Dynamic path relativization and cross-machine absolute path remapping engine. — PathRelativizer: Pure heuristic path relativization and cross-machine remapping engine. | ✅ |

## Key Dependencies

- External libraries: `pydantic`, `langchain_core`
