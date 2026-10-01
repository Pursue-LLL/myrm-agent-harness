# core/security/ocap/

## Overview
Object-Capability (OCap) zero-trust delegation mesh primitives. Eliminates ambient authority by ensuring every agent operation is mediated by an unforgeable, cryptographically signed, short-lived `CapabilityHandle`. Supports mathematical one-way capability attenuation (subset restriction) and instant cascading revocation across subagent trees.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public export facade for all OCap primitives. | ✅ |
| `types.py` | Core | Foundation type contracts: `CapabilityAction`, `ResourceScope`, `CapabilityHandle`, `AttenuationError`, `CapabilityDeniedError`. | ✅ |
| `token.py` | Core | HMAC-SHA256 signature calculation, verification, and timing-safe comparison. | ✅ |
| `attenuation.py` | Core | One-way capability attenuation pipeline (`attenuate_capability`, `validate_scope_subset`). Blocks permission elevation. | ✅ |
| `registry.py` | Core | Sharded concurrent lifecycle registry (`CapabilityRegistry`) with instant cascading tree revocation and monotonic TTL pruning. | ✅ |
| `context.py` | Core | Async-safe ContextVar management (`capability_scope`, `get_current_capability`). | ✅ |
| `guard.py` | Core | Execution-layer enforcement guard (`check_capability_access`, `enforce_capability_access`) for file ops, bash, network, and MCP. | ✅ |

## Architectural Invariants
1. **Zero Ambient Authority**: Agents do not inherit system privileges by default; operations require explicit capability presence.
2. **One-Way Attenuation**: Child capabilities can only stay equal or narrow; any permission elevation raises `AttenuationError`.
3. **Instant Cascading Revocation**: Revoking a parent handle instantly invalidates all its descendant handles in O(1) time.
4. **Prompt Cache Protection**: Capabilities exist purely in Python runtime ContextVar and metadata, never polluting LLM system prompts.
