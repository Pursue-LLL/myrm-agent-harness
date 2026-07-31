# skills/

## Overview
Skills runtime — skill execution and management. Bound skill catalog delivery lives in `runtime/skill_catalog_delivery.py` (first HumanMessage ``<bound_skills>``); see `runtime/_ARCH.md` and `meta_tools/skills/select/_ARCH.md`.

Detailed design: [SKILL_SYSTEM.md](SKILL_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skills runtime — skill execution and management. | — |

| Submodule | Description |
|-----------|-------------|
| curator/ | Skill Curator — automated lifecycle governance (stale/archive transitions). |
| market/ | Skill market — search, install, update from external sources. |
| evolution/ | Skill Evolution System - Framework Layer. |
| history/ | Skill modification history tracking with pluggable backends. |
| mcp/ | MCP Skills — Agent-layer MCP skill transformation. |
| optimization/ | Skill Optimization Toolkit |
| packaging/ | Skill packaging (ZIP export/import) and validation. |
| runtime/ | Runtime — skill execution runtime. |
| security/ | Export-time content sanitization for skill privacy protection. |

## Key Dependencies

- `backends`
