# analyze/

## Overview
Skill analysis meta tool for identifying low-quality skills. Registered as **deferred** in `get_meta_tools()` (not in Turn-1 schema). Primary lifecycle cleanup is server Curator + WebUI; mount via `discover_capability_tool` when the user asks in chat.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill analysis meta tool for identifying low-quality skills. | — |
| skill_analyze_tool.py | Core | Forgetting/stale-skill diagnostics (**deferred** in get_meta_tools). | ✅ |

## Key Dependencies

- `backends`
