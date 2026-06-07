# agent/_factory/

## Overview
Internal SkillAgent factory assembly — MCP routing and runtime wiring.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `mcp_routing.py` | Core | MCP hybrid direct vs PTC routing by schema token cost + aggregate budget guard | ✅ |
| `builder.py` | Core | `create_skill_agent` assembly pipeline | ✅ |
| `__init__.py` | Package | Re-exports `create_skill_agent` | ✅ |

## Import Conventions

- Public factory: `agent.skill_agent_factory` or `myrm_agent_harness.api.create_skill_agent`
- MCP routing test helpers: `agent._factory.mcp_routing` (not re-exported via facade)

## Dependencies

- `agent.skill_agent`, `agent.types`
- `toolkits.mcp`, `toolkits.openapi_bridge`, `backends.skills`
