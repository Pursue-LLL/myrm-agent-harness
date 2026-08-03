# agent/_factory/

## Overview
SkillAgent factory assembly — MCP routing, surface mode, OpenAPI direct bind, and `create_skill_agent` pipeline.

## MCP routing (two outcomes only)

| File | Role | Description |
|------|------|-------------|
| `mcp_routing.py` | Core | **Direct FC** vs **MCP→Skill (PTC)** by per-server schema + aggregate budget (`AGGREGATE_DIRECT_TOKEN_BUDGET=1200`). Clears MCP entries in `skill_registry` before routing. Returns `MCPRoutingResult(skills, direct_tools)`. |
| `mcp_surface.py` | Core | `MCPSurfaceMode`: `auto` \| `direct_fc`. Legacy `catalog_invoke` profile values parse as `auto` with warning. |
| `builder.py` | Core | Wires routing into `create_skill_agent`. Clears MCP registry when `mcp_servers` is empty. OpenAPI direct bind raises `ConfigIncompleteError` when enabled services produce zero tools or schema exceeds aggregate budget. |

```
route_mcp_servers()
  ├─ clear_mcp_skills() in skill_registry
  ├─ per-server schema > direct_threshold → MCP→Skill (PTC)
  ├─ aggregate direct pool > 1200 tok (auto) → demote largest servers → MCP→Skill
  └─ else → Direct FC Turn1 bind

create_skill_agent() OpenAPI path
  ├─ enabled services but 0 tools loaded → ConfigIncompleteError (openapi_load_failed)
  ├─ schema ≤ 1200 tok → Turn1 direct tools
  └─ schema > 1200 tok (non direct_fc) → ConfigIncompleteError (openapi_direct_budget_exceeded)
```

**Forbidden**: catalog_invoke / capability_invoke proxy / RUNTIME MCP pools — see `TOOL_DESIGN_STRATEGY.md` §MCP 路由铁律.

## Verification

| Layer | Tests |
| --- | --- |
| Unit | `tests/agent/_factory/test_builder_openapi_load_failed.py`, `test_builder_openapi_budget.py`, `test_builder_mcp_registry_clear.py` |
| Integration | `tests/integration/test_openapi_fail_loud_integration.py` |
| Architecture gate | `tests/architecture/test_openapi_fail_loud_gate.py`, `test_mcp_routing_two_outcomes.py` |
| Chrome E2E (server) | `myrm-agent-server/tests/e2e/test_openapi_fail_loud_chrome_e2e.py` — load_failed + budget_exceeded UI SSE |
