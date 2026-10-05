# core/hooks/

## Overview
Framework-agnostic hook lifecycle definitions. Provides HookEvent enum, hook definition variants (Callable/Command/HTTP/LLM), HookResult, and event payload dataclasses.

## Governance Model

Every hook carries two governance fields (defined on `_HookBase`):
- `priority` — execution order within an event; higher runs first, ties keep registration order (onion model). Safety hooks use `HOOK_PRIORITY_SECURITY` and their decisions (block / `updated_input`) cannot be overridden by lower-priority hooks.
- `source` — provenance tag (`builtin` / `skill` / `plugin` / `user_config`) driving audit metadata and the command gate's strictness: hooks from third-party provenance get the narrower gate path because they fire silently.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports all hook types and payloads. | ✅ |
| types.py | Core | HookEvent (StrEnum, 17 events), HookDefinition (Union of 4 variants, each with `priority`/`source` governance fields), HookResult/AggregatedHookResult (dataclasses with elapsed_ms timing), HookSource enum + HOOK_PRIORITY_SECURITY constant, event payload dataclasses, HookRegistryProtocol (runtime_checkable Protocol for cross-layer DI). | ✅ |

## Key Dependencies

- No internal dependencies (foundation layer)
