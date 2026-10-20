# skills/

## Overview
Skills runtime — skill execution and management. Bound skill catalog delivery lives in `runtime/skill_catalog_delivery.py` (a frozen ``<bound_skills>`` baseline on the first HumanMessage of a rebuilt conversation, a ``<bound_skills_update>`` tail on a later one); see `runtime/_ARCH.md` and `meta_tools/skills/select/_ARCH.md`.

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
| mcp/ | MCP Skills — Agent-layer MCP skill transformation. |
| optimization/ | Skill Optimization Toolkit |
| packaging/ | Skill packaging (ZIP export/import) and validation. |
| runtime/ | Runtime — skill execution runtime. |
| security/ | Export-time content sanitization for skill privacy protection. |
| autonomous_visualization/ | Autonomous Zero-Prompt Visualization & Dynamic Web Dashboard Engine (Item 49 P1). |
| bundle_warmup/ | 技能包清单化一键批量加载与运行时生命周期预热管理器 (Item 41 P1). |

## Key Dependencies

- `backends`
