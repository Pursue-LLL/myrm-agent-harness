# agent/_factory/

## Overview
Internal SkillAgent factory assembly — two-path MCP routing and runtime wiring.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `mcp_routing.py` | Core | MCP two-path routing (direct/PTC) by schema token cost + aggregate budget guard + direct-tool description compaction. Returns `MCPRoutingResult`. | ✅ |
| `builder.py` | Core | `create_skill_agent` assembly pipeline; accepts `on_loaded_skills_persist` hook for server-layer session skill SSOT | ✅ |
| `__init__.py` | Package | Re-exports `create_skill_agent` | ✅ |

## Routing Architecture

```
MCP Server → per-server token estimate
  ├─ ≤ threshold AND aggregate ≤ budget → Direct (full schema in tools array)
  └─ > threshold OR aggregate > budget → PTC/Skill (skill_search → skill_select → PTC)
```

## Import Conventions

- Public factory: `agent.skill_agent_factory` or `myrm_agent_harness.api.create_skill_agent`
- MCP routing test helpers: `agent._factory.mcp_routing` (not re-exported via facade)
- Tests: `tests/agent/_factory/test_mcp_routing_route.py`, `tests/toolkits/mcp/test_hybrid_invocation.py`

## Dependencies

- `agent.skill_agent`, `agent.types`
- `toolkits.mcp`, `toolkits.openapi_bridge`, `backends.skills`
