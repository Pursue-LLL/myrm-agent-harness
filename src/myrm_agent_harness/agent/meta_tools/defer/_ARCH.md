# meta_tools/defer/

Cache-safe deferred native tool schema gateway.

| File | Tier | Purpose | Status |
| --- | --- | --- | --- |
| `invoke_deferred_tool.py` | Core | Turn1-bound schema gateway. `DeferredToolMiddleware` rewrites valid calls to the effective target before approval; direct fallback is fail-closed. | ✅ |

**Related:** `tool_management/defer/` (economics, stable index, hit parsing); `middlewares/deferred_index_middleware.py`.
