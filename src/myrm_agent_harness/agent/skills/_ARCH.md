# skills/

## Overview
Skills runtime — skill execution and management.

Detailed design: [SKILL_SYSTEM.md](SKILL_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skills runtime — skill execution and management. | — |

| Submodule | Description |
|-----------|-------------|
| curator/ | Skill Curator — automated lifecycle governance (stale/archive transitions). |
| discovery/ | Skill discovery module. |
| evolution/ | Skill Evolution System - Framework Layer. |
| history/ | Skill modification history tracking with pluggable backends. |
| mcp/ | MCP Skills — Agent-layer MCP skill transformation. |
| optimization/ | Skill Optimization Toolkit |
| packaging/ | Skill packaging (ZIP export/import) and validation. |
| runtime/ | Runtime — skill execution runtime. |
| security/ | Export-time content sanitization for skill privacy protection. |

## Key Dependencies

- `backends`
