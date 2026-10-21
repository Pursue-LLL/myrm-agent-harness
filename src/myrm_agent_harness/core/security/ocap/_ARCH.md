# core/security/ocap/

## Overview
Object-Capability (OCap) primitives for subagent confinement. The production producer is `agent/sub_agents/spawn_capability.derive_spawn_capability`: one unforgeable, HMAC-signed `CapabilityHandle` per subagent spawn, bound to the child run with `capability_scope` for the spawn's whole lifetime (the only channel: executors and grandchild derivation read the same ContextVar) and enforced by the file executors (read/write) and the local shell and Python executors (execute; a handle without WRITE makes the workspace read-only for them, backed by the OS sandbox where one is available). It is what keeps a `readonly` subagent or a verifier from writing through the file and shell tools. A verifier's handle comes from `spawn_capability.derive_verifier_capability`: the delegating agent's reach restricted to READ and EXECUTE. The capability vocabulary is exactly what production enforces: READ, WRITE and EXECUTE over path patterns. Validity is stateless (signature and expiry); nothing is registered or retained per spawn, and the signing key is random per process, never configured or persisted.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public export facade for all OCap primitives. | ✅ |
| `types.py` | Core | Foundation type contracts: `CapabilityAction`, `ResourceScope`, `CapabilityHandle`, `AttenuationError`, `CapabilityDeniedError`. | ✅ |
| `token.py` | Core | HMAC-SHA256 signature calculation, verification, and timing-safe comparison. | ✅ |
| `attenuation.py` | Core | One-way capability attenuation pipeline (`attenuate_capability`, `validate_scope_subset`) and the shared path-boundary test (`_is_path_subscope`: lexical match verified against realpath, symlinked aliases resolved by physical containment). | ✅ |
| `context.py` | Core | Async-safe ContextVar management (`capability_scope`, `get_current_capability`). | ✅ |
| `guard.py` | Core | Execution-layer enforcement guard (`check_capability_access`, `enforce_capability_access`) for the local file and shell executors. | ✅ |
| `registry.py` | Core | Concurrent sharded capability registry with instant cascading revocation. — CapabilityRegistry: Thread-safe, sharded O(1) lifecycle and revocation registry; get_default_capability_registry: Global thread-safe singleton getter | ✅ |

## Architectural Invariants
1. **Fail-Closed When Bound**: A bound handle that is expired, unsigned, out of scope or lacking the action denies the operation. EXECUTE is checked against the working directory only; the command text is bounded by the executor's command validator, not by the handle. With no handle bound (the top-level agent), operations are unconstrained.
2. **Physical Containment**: A path is in scope when it lies under a scope path lexically and, when it exists, still resolves inside it, or when its symlink-resolved location lies inside the scope's existing directory. A workspace root and its symlinked alias are one boundary, whichever form an executor presents; a symlink leading out of the boundary is denied.
3. **Spawn-Lifetime Validity**: A spawn handle stays valid across every attempt, retry and verification round of its spawn, because background subagents outlive the spawn scope; the 24-hour expiry only bounds a leaked handle.
4. **One-Way Attenuation**: `attenuate_capability` only narrows; any elevation raises `AttenuationError`. A spawn from an already confined parent is attenuated from the parent's handle, so a child never exceeds its parent, and a read-only parent only spawns read-only children.
5. **Authoritative Scope Source**: The scope root is the parent's own workspace, never a value the model supplies. `context_files` extend it only for paths the parent's path policy and session access grants already allow (and the parent handle's read scope, for a spawned parent); the model's `context` reaches the child as task text only, never as runtime context.
6. **Prompt Cache Protection**: Capabilities exist purely in Python runtime ContextVar and metadata, never polluting LLM system prompts.
