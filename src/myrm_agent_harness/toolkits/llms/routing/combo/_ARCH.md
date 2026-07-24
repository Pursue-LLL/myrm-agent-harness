# combo/

## Overview

Combo routing engine — single source of truth for LLM target selection and failover. A *Combo* is an ordered chain of provider/model targets with automatic failover when a target exhausts its quota, hits a rate limit, or encounters an error.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public re-exports | — |
| combo_types.py | Core | Pydantic data models: `ComboConfig`, `ComboTarget`, `RoutingStrategy` (7 strategies) | ✅ |
| strategies.py | Core | Pure strategy functions that reorder targets. `StrategyContext` carries session state (LKGP sticky, round-robin index, request counts) | ✅ |
| resolver.py | Core | `ComboResolver` — stateful per-session resolver that walks the chain, integrates `CredentialPool` for key rotation, and tracks per-target cooldowns | ✅ |

## Key Dependencies

- `llms.core.credential_pool` — multi-key dispatch and cooldown within a single provider

## Design Notes

- **Framework-level**: No business logic. Consumed by Server `passthrough.py` and Agent profile resolution.
- **CredentialPool integration**: Each target gets its own `CredentialPool` instance. Key rotation happens *within* a target before the resolver slides to the next target in the chain.
- **Strategies are pure**: `apply_strategy()` is a pure function — it reorders targets based on `StrategyContext` without I/O. The resolver manages the context lifecycle.
- **Cooldown stacking**: Target-level cooldown (exponential backoff) stacks with credential-level cooldown from `CredentialPool`. A target is only skipped when *all* its keys are cooled down.
- **Empty Combo fallback**: An empty `ComboConfig` (no targets) is valid — the caller (e.g. passthrough) falls back to single-provider resolution.
