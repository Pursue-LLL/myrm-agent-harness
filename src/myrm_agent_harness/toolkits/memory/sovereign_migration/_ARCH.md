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

## Key Dependencies

- External libraries: `pydantic`, `langchain_core`
