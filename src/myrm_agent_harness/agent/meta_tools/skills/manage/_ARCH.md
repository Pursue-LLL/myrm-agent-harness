# manage/

## Overview
Skill management meta tool. Supports optional similarity checking to warn about semantically duplicate skills on save.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill management meta tool. | — |
| lock_manager.py | Core | Provides per-skill lock mechanism to prevent concurrent modifications. | ✅ |
| skill_manage_tool.py | Core | Skill management meta tool facade and factory function. | ✅ |
| _manage_handlers.py | Core | Action execution handlers (save/patch/delete/write_file/remove_file/lock/unlock) and validators. | ✅ |

## Key Dependencies

- `backends`
- `utils`
