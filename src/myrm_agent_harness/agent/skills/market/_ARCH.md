# market/

## Overview
Skill market module — search, install, update, and manage skills from external sources.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill market module. | — |
| autoupdate.py | Core | Skill auto-update checker. | ✅ |
| helpers.py | Core | Skill market helper functions (write_origin with parent_plugin & declared_mcp_servers provenance, ranking, dedup). | ✅ |
| sanitizer.py | Core | Provides is_blocked_file, sanitize_skill_files. | ✅ |
| service.py | Core | Skill market service with deterministic multi-source merge, canonical archive-security mapping, dynamic source registration, Agent Plugins 1.0.0 multi-skill unpack & preview/install MCP transparency, cascading uninstall, and managed receipt generation. | ✅ |
| transaction.py | Core | Skill installation transaction and snapshot rollback manager with immutable receipt builder. | ✅ |

| Submodule | Description |
|-----------|-------------|
| installers/ | Skill installers. |
| sources/ | Skill data sources. |

## Key Dependencies

- `backends`
