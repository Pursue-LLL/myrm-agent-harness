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
| registry.py | Core | Tool safety SSOT — TOOL_PERMISSION_MAP, BUILTIN_TOOL_NAMES, TOOL_GROUP_MAP/TOOL_TO_GROUP/TOOL_GROUP_NAMES, TOOL_CANONICAL_PARAMS, TOOL_SAFETY_METADATA, SafetyMetadata, MCPAnnotations, resolve_safety_metadata/resolve_permission_type/compute_canonical_args_hash, PTC dynamic registration, module-load safety gate. | ✅ |
| safety.py | Core | `check_safety_coverage()` — module-load warning when built-in tools lack TOOL_SAFETY_METADATA entries. | ✅ |

## Key Dependencies

- None within `core.security` (foundation layer); `safety.py` lazily imports `registry.py` from within the function body to avoid a load-time cycle.

## Consumers

- `agent/security/tool_registry.py` — thin facade re-exporting public + private symbols
- `agent/middlewares/` (safety_dispatcher, concurrency_router, approval, _runtime_tool_governance) — permission/safety resolution
- `toolkits/mcp/tool_processing.py` — PTC dynamic safety registration
- `backends/skills/_runtime.py` — TOOL_GROUP_NAMES for skill conditional activation
- `tests/agent/security/test_tool_registry.py` — monkeypatches `registry.BUILTIN_TOOL_NAMES` + logs via `core.security.tool_registry.safety`
