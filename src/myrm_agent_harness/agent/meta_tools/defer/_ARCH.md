# meta_tools/defer/

Cache-safe deferred native tool execution proxy.

| File | Tier | Purpose | Status |
| --- | --- | --- | --- |
| `invoke_deferred_tool.py` | Core | Turn1-bound `invoke_deferred_tool` proxy; executes `DISCOVERABLE` tools without mutating `bind_tools`. | ✅ |

**Related:** `tool_management/defer/` (economics, stable index, hit parsing); `middlewares/deferred_index_middleware.py`.
