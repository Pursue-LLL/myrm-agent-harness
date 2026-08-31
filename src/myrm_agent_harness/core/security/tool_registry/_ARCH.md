# tool_registry/

## Overview

Tool metadata registry domain — the SSOT for built-in tool names, permission-type
mapping, canonical params, safety metadata, and canonical tool-group mapping.
Two files by concern: `registry.py` holds the tool safety SSOT and PTC dynamic
registration; `safety.py` is the module-load coverage gate warning when built-in
tools lack explicit safety declarations. `__init__.py` is the aggregation facade
preserving the flat-module import surface for all consumers.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregation facade — re-exports registry + safety public/internal symbols. | ✅ |
| registry.py | Core | Tool safety SSOT — TOOL_PERMISSION_MAP, BUILTIN_TOOL_NAMES, TOOL_GROUP_MAP/TOOL_TO_GROUP/TOOL_GROUP_NAMES, TOOL_CANONICAL_PARAMS, TOOL_SAFETY_METADATA, AUTO_APPROVED_BUILTIN_TOOLS/AUTO_APPROVE_REASONS/RULESET_COVERAGE_WHITELIST/EXPLICIT_MCP_FALLBACK_TOOLS/DYNAMICALLY_RESOLVED_TOOL_NAMES (governance audit declarations), SafetyMetadata, MCPAnnotations, resolve_safety_metadata/resolve_permission_type/compute_canonical_args_hash, PTC dynamic registration & thread-safe eviction (`unregister_ptc_safety_metadata` / `evict_skill_safety_metadata`), module-load safety gate. | ✅ |
| safety.py | Core | `check_safety_coverage()` — module-load warning when built-in tools (BUILTIN_TOOL_NAMES ∪ EXPLICIT_MCP_FALLBACK_TOOLS) lack TOOL_SAFETY_METADATA entries. Scope mirrors the CI governance gate. | ✅ |

## Governance Coverage Declarations

Built-in tools NOT in `TOOL_PERMISSION_MAP` and NOT covered by a dynamic
`resolve_permission_type()` branch MUST be declared in
`AUTO_APPROVED_BUILTIN_TOOLS` with a reason from `AUTO_APPROVE_REASONS`.
Permission types produced by `TOOL_PERMISSION_MAP` without an explicit
`DEFAULT_RULESET` rule MUST be declared in `RULESET_COVERAGE_WHITELIST`.
These declarations are audit metadata consumed by
`scripts/validate_tool_registry.py` (CI gate); they do not change runtime
permission resolution. Adding a built-in tool that silently bypasses governance
fails the CI gate.

The gate iterates the **registered built-in universe** (CORE/HIGH_PRIORITY/EXTENDED
layers of `_TOOL_LAYERS` + server bootstrap), not the static
`BUILTIN_TOOL_NAMES` whitelist. A registered tool is covered when it has a
permission mapping, a dynamic resolver branch (its name must be in
`DYNAMICALLY_RESOLVED_TOOL_NAMES` — the single source of truth for
`resolve_permission_type()` sub-action branches, consumed by the gate so the
list cannot drift), an `AUTO_APPROVED_BUILTIN_TOOLS`
declaration, or an `EXPLICIT_MCP_FALLBACK_TOOLS` declaration (intentional
`mcp_invoke=ASK` for high-blast-radius tools that must NOT be promoted to their
own name — promoting would flip the runtime baseline to ALLOW). The gate also
enforces bidirectional consistency: `BUILTIN_TOOL_NAMES` must be a subset of
the registered built-in universe, and must not overlap
`EXPLICIT_MCP_FALLBACK_TOOLS`. EXTERNAL-layer tools are server vendor tools
governed by the server layer; the harness gate only annotates them as
`server_managed` and never forces a declaration on them.

## Key Dependencies

- None within `core.security` (foundation layer); `safety.py` lazily imports `registry.py` from within the function body to avoid a load-time cycle.

## Consumers

- `agent/security/tool_registry.py` — thin facade re-exporting public + private symbols
- `agent/middlewares/` (safety_dispatcher, concurrency_router, approval, _runtime_tool_governance) — permission/safety resolution
- `toolkits/mcp/tool_processing.py` — PTC dynamic safety registration
- `backends/skills/_runtime.py` — TOOL_GROUP_NAMES for skill conditional activation
- `tests/agent/security/test_tool_registry.py` — monkeypatches `registry.BUILTIN_TOOL_NAMES` + logs via `core.security.tool_registry.safety`
