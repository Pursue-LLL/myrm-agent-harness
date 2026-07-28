# agent/_factory/

## Overview
Internal SkillAgent factory assembly — three-path MCP routing and runtime wiring.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `mcp_routing.py` | Core | MCP three-path routing (direct/bridge/PTC) by schema token cost + aggregate budget guard + direct-tool description compaction. Returns `MCPRoutingResult`. | ✅ |
| `tool_search_bridge.py` | Core | Tool Search Bridge — progressive disclosure for deferred MCP tools. BM25 catalog + 3 bridge tools (`mcp_tool_search`/`mcp_tool_describe`/`mcp_tool_call`) retaining native FC. | ✅ |
| `builder.py` | Core | `create_skill_agent` assembly pipeline; accepts `on_loaded_skills_persist` hook for server-layer session skill SSOT | ✅ |
| `__init__.py` | Package | Re-exports `create_skill_agent` | ✅ |

## Routing Architecture

```
MCP Server → per-server token estimate
  ├─ ≤ threshold AND aggregate ≤ budget → Direct (full schema in tools array)
  ├─ ≤ threshold BUT aggregate > budget → Bridge (deferred native FC via 3 meta-tools)
  └─ > threshold (mega server) → PTC/Skill (SOP-driven, via skill_select_tool)
```

## Import Conventions

- Public factory: `agent.skill_agent_factory` or `myrm_agent_harness.api.create_skill_agent`
- MCP routing test helpers: `agent._factory.mcp_routing` (not re-exported via facade)
- Bridge internals: `agent._factory.tool_search_bridge` (session-scoped catalog)

## Dependencies

- `agent.skill_agent`, `agent.types`
- `toolkits.mcp`, `toolkits.openapi_bridge`, `backends.skills`
