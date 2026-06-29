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
| http_executor.py | Core | Async HTTP executor via `secure_request` (SSRF + redirect-safe). Path params, auth, timeout/retry. | ✅ |
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

6. **Ephemeral User Credentials Propagation**: `OpenAPIExecutor` integrates with
   `user_credentials_ctx` to intercept requests, dynamically override the Bearer token with
   the context-bound user token matching the service name, and perform preemptive and
   reactive (on 401 response) token refresh using the bound refresh callback.

