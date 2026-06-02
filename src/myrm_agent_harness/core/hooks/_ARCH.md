# core/hooks/

## Overview
Framework-agnostic hook lifecycle definitions. Provides HookEvent enum, hook definition variants (Callable/Command/HTTP/LLM), HookResult, and event payload dataclasses.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports all hook types and payloads. | ✅ |
| types.py | Core | HookEvent (StrEnum), HookDefinition (Union of 4 variants), HookResult/AggregatedHookResult (dataclasses), 11 event payload dataclasses, HookRegistryProtocol (runtime_checkable Protocol for cross-layer DI). | ✅ |

## Key Dependencies

- No internal dependencies (foundation layer)
