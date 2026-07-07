# defer/

Unified deferred-tool activation: economics, stable index, invoke gateway.

| File | Tier | Purpose | Status |
| --- | --- | --- | --- |
| `economics.py` | Core | `should_bind_discover_gateway` — Turn1 discover binding when net-positive (skills / >2 defer / large schema). | ✅ |
| `stable_index.py` | Core | `<available-deferred-tools>` stable system prompt section; sorted names only. | ✅ |
| `activation.py` | Core | Parse `<DeferredToolHits>` from discover output. | ✅ |

**Related (not in this folder):**

- `meta_tools/defer/invoke_deferred_tool.py` — Turn1-bound gateway for DISCOVERABLE native tools.
- `middlewares/deferred_index_middleware.py` — injects stable index once per thread.
- `middlewares/deferred_tool_middleware.py` — ToolNode resolution only; no `request.tools` mutation.

**Design:** Framework 11.1 — never append deferred schemas to `bind_tools`; use `invoke_deferred_tool` + stable index.
