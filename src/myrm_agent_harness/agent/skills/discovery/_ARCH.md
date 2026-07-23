# discovery/

## Overview
Skill discovery module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill discovery module. | — |
| autoupdate.py | Core | Skill auto-update checker. | ✅ |
| helpers.py | Core | Skill discovery helper functions. | ✅ |
| sanitizer.py | Core | Provides is_blocked_file, sanitize_skill_files. | ✅ |
| service.py | Core | Skill discovery service with deterministic multi-source merge (source-priority stable dedup), canonical archive-security mapping, and machine-readable install `error_code` output. | ✅ |

| Submodule | Description |
|-----------|-------------|
| installers/ | Skill installers. |
| sources/ | Skill data sources. |

## Key Dependencies

- `backends`
