# skills/

## Overview
Agent meta-tools for skills (select, search, manage, discovery). Bound skill **catalog** is injected on the first HumanMessage via `agent/skills/runtime/skill_catalog_delivery.py` (see `select/_ARCH.md`); `skill_select_tool.description` stays byte-stable. Skill hygiene / stale cleanup → WebUI **Curator** (`curator_service.py`), not an Agent tool.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |

| Submodule | Description |
|-----------|-------------|
| discovery/ | Skill discovery meta-tool. |
| manage/ | Skill management meta tool. |
| search/ | Skill search module. |
| select/ | Skill selection tool module. |
