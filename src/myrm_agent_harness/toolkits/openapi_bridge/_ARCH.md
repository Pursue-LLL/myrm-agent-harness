# openapi_bridge/

## Overview
OpenAPI Bridge toolkit. Provides zero-code REST API integration via OpenAPI 3.x
and Swagger 2.0 specifications. Parses specs, generates LangChain StructuredTool
instances with namespace isolation, and handles HTTP execution with authentication.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | OpenAPI Bridge toolkit entry point. Exports bridge facade, config models, and parser functions. | ✅ |
| config.py | Config | Configuration models: OpenAPIServiceConfig, AuthConfig, AuthType, ParsedEndpoint. | ✅ |
| spec_parser.py | Core | OpenAPI 3.x / Swagger 2.0 parser. Fetches remote specs via `core.security.http.secure_fetch`. | ✅ |
| auth.py | Core | Authentication resolver: API Key, Bearer, Basic, OAuth2 client_credentials. Caches OAuth2 tokens. | ✅ |
| http_executor.py | Core | Async HTTP executor via `secure_request` (SSRF + redirect-safe). Path params, auth (incl. ephemeral user credential injection), timeout/retry. | ✅ |
| param_schema.py | Core | Merged per-endpoint parameter JSON Schema extraction (path/query/body) with local `$ref` inlining via `mcp.schema.normalize::flatten_json_schema`. | ✅ |
| tool_generator.py | Core | Endpoint → StructuredTool converter. Namespace isolation, parameter schema propagation. OpenAPIBridge facade. | ✅ |

## Key Dependencies

- `httpx` — async HTTP client
- `PyYAML` — YAML spec parsing
- `pydantic` — configuration models
- `langchain_core` — StructuredTool base

## Architecture

```
OpenAPIServiceConfig (user config)
        │
        ▼
   spec_parser.py ──► ParsedSpec (endpoints, tags, base_url)
        │
        ▼
  tool_generator.py ──► list[StructuredTool]
        │                    │
        │              (each tool bound to)
        ▼                    ▼
   http_executor.py ◄── auth.py
        │
        ▼
   HTTP Response → formatted string
```

## Design Decisions

1. **Parallel to MCP, not nested**: OpenAPI Bridge is a separate toolkit alongside MCP.
   Both produce `list[BaseTool]` consumed by the same ToolRegistry/ActionSpaceProfiler.

2. **Namespace isolation**: Tool names use `{service_name}_{operation_id}` pattern to
   prevent collisions when multiple OpenAPI services are configured.

3. **Endpoint selection**: Users choose specific endpoints rather than importing all.
   Prevents token explosion on large APIs (e.g., Stripe has 300+ endpoints).

4. **OAuth2 token caching**: Tokens cached until 90% of expiry time to minimize
   token refresh roundtrips.

5. **Swagger 2.0 support**: Internal conversion to unified representation enables
   supporting legacy APIs without dual code paths.

6. **Schema-driven parameter extraction & coercion**: `param_schema.py` merges
   path/query/body parameters (OpenAPI 3.x `parameters` + `requestBody`, Swagger 2.0
   `in: body`) into a per-endpoint JSON Schema (`ParsedEndpoint.param_schema`) with
   path/query key sets for exact dispatch. Local `$ref` pointers
   (`#/components/schemas/...`, `#/components/parameters/...`,
   `#/components/requestBodies/...`, `#/definitions/...`, Swagger 2.0 top-level
   `#/parameters/...`) are resolved inline via `flatten_json_schema` (shared with
   MCP schema normalization) plus `param_schema.py`'s own pointer walker;
   unresolvable external refs degrade to permissive schemas so strict providers never
   receive a bare `$ref`. `tool_generator` builds the tool's `args_schema` from this
   schema and runs `coerce_arguments_by_schema` (shared with MCP, from
   `mcp/schema/coerce.py`) on LLM-emitted arguments before dispatch — string `"25"` →
   `int 25`, big-int precision preserved, float-form whole literals (`"25.0"`, `"1e3"`,
   `"9007199254740993.0"`) → exact `int` via `Decimal` (never rounded through
   `float()`), non-finite values (`inf`/`nan`/absurd exponents) kept as strings — so
   strict typed APIs never receive stringified or precision-lost numbers. Schema-less
   specs fall back to the legacy path-only / method-based dispatch. Body parameters
   declared as primitives/arrays (spec `body` param, `_body`, `request_body`) are sent
   as the request body directly, never wrapped — residual string bodies go verbatim
   unless they parse to a JSON container (weak-model stringified objects); query values
   serialize by type (objects/arrays → compact JSON, booleans → lowercase, scalars →
   plain string) and null values are omitted from the query string.

7. **Ephemeral User Credentials Propagation**: `OpenAPIExecutor` integrates with
   `user_credentials_ctx` to intercept requests, dynamically override the Bearer token with
   the context-bound user token matching the service name, and perform preemptive and
   reactive (on 401 response) token refresh using the bound refresh callback.

8. **Turn1 direct budget**: When generated tool schemas exceed `AGGREGATE_DIRECT_TOKEN_BUDGET`
   (1200 tokens, shared with MCP direct routing), `create_skill_agent` raises
   `ConfigIncompleteError` (`openapi_direct_budget_exceeded`). Reduce selected endpoints in
   Agent settings — no silent skip.

9. **Turn1 load failure**: When one or more OpenAPI services are enabled but loading produces
   zero tools (bad spec, auth, or endpoint selection), `create_skill_agent` raises
   `ConfigIncompleteError` (`openapi_load_failed`) — no silent zero-tool agent.

## Verification

| Layer | Tests |
| --- | --- |
| Unit / integration | `tests/agent/_factory/test_builder_openapi_*.py`, `tests/integration/test_openapi_fail_loud_integration.py` |
| Chrome E2E | `myrm-agent-server/tests/e2e/test_openapi_fail_loud_chrome_e2e.py` |
