# market/

## Overview
Skill market module — search, install, update, and manage skills from external sources.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill market module. | — |
| autoupdate.py | Core | Skill auto-update checker. | ✅ |
| helpers.py | Core | Skill market helper functions. | ✅ |
| sanitizer.py | Core | Provides is_blocked_file, sanitize_skill_files. | ✅ |
| service.py | Core | Skill market service with deterministic multi-source merge (source-priority stable dedup), canonical archive-security mapping, dynamic source registration (register_source/unregister_source), and machine-readable install `error_code` output. | ✅ |

| Submodule | Description |
|-----------|-------------|
| installers/ | Skill installers. |
| sources/ | Skill data sources. |

## Key Dependencies

- `backends`
