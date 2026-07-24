# routing/

## Overview

Pre-agent routing layer. Determines which LLM tier/model to use before Agent creation. Also provides the **ComboResolver** — the single source of truth for multi-target LLM routing with automatic failover, consumed by both Agent profiles and the Passthrough gateway.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Lazy-import init | — |
| complexity_router.py | Core | Two-phase (rule+LLM judge) task complexity routing with session momentum. Selects SIMPLE/STANDARD/REASONING model tier. | ✅ |
| privacy_routing.py | Core | Privacy-aware model routing. Routes to appropriate models based on PII sensitivity levels. | ✅ |

| Submodule | Description |
|-----------|-------------|
| combo/ | Combo routing engine — ordered target chains with 7 strategies (priority, cost_optimized, round_robin, random, lkgp, context_relay, headroom), per-target CredentialPool integration, and automatic cooldown/failover. |

## Key Dependencies

- `agent.config` (LLMConfig)
- `llms.core.credential_pool` (CredentialPool — used by combo/)

## Design Notes

- **Momentum**: `complexity_router` supports session momentum — short follow-up messages inherit the conversation's recent routing tier to prevent quality degradation during multi-turn complex tasks.
- **Min-tier floor**: `route_task(min_tier=...)` enforces a minimum tier regardless of classification result. Used by callers for complaint-up escalation (regenerate → automatic tier upgrade).
- **Penalty feedback**: `record_misroute(tier)` records misrouted tiers so PenaltyTracker reduces future misrouting probability (24h decay).
- **Cache-friendly**: Routing runs before Agent creation, so it does not affect system prompt cache hit rates.
- **Extensible**: All routers accept custom keyword sets and configuration overrides via function parameters.
- **Combo SSOT**: The `combo/` submodule is the unified routing engine for both Agent and Passthrough paths. It does not duplicate `ModelFallbackManager` (which handles intra-call retry at the LangChain level) but sits above it as the *target selection* layer. A `ComboResolver` instance is stateful per-session, tracking LKGP sticky targets, round-robin indices, and per-target cooldowns.
