# schema/

## Overview
MCP inbound tool schema normalization: cache-stable canonicalization, `$ref` resolution, deep-nesting flattening, composite-keyword collapsing, and LLM-emitted argument coercion before dispatch.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Sub-package exports. | — |
| normalize.py | Core | `flatten_json_schema` ($ref/$defs resolution), `canonicalize_schema_for_cache` (deterministic key ordering for prompt prefix cache stability), `analyze_schema_complexity`, `flatten_deep_schema` / `has_dot_keys` / `nest_flat_arguments` (deep-nesting flattening to dot-path notation). | ✅ |
| composite.py | Core | `collapse_const_unions` (property-level `anyOf`/`oneOf` same-typed `const` unions → `enum`) and `flatten_top_level_composite` (top-level `anyOf`/`oneOf`/`allOf` object branches → flat `properties` with conjunctive/alternative merge semantics). | ✅ |
| coerce.py | Core | `coerce_arguments_by_schema` dynamic type coercion (string "100" → int, "true" → bool, container literals), strict-host required+nullable explicit-`None` completion, and null optional field stripping via `prepare_mcp_call_arguments`. Lightweight observability counters. | ✅ |

## Key Dependencies

- `utils.json_parsing`
- `toolkits.mcp.tool_processing` (tolerance chain invocation)
