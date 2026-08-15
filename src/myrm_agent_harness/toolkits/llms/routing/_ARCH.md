# routing/

## Overview

Pre-agent routing layer. Determines which LLM tier/model to use before Agent creation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Lazy-import init | — |
| complexity_router.py | Core | Two-phase (rule+LLM judge) task complexity routing with session momentum. Selects SIMPLE/STANDARD/REASONING model tier. | ✅ |
| privacy_routing.py | Core | Privacy-aware model routing. Routes to appropriate models based on PII sensitivity levels. | ✅ |

## Key Dependencies

- `agent.config` (LLMConfig)

## Design Notes

- **Momentum**: `complexity_router` supports session momentum — short follow-up messages inherit the conversation's recent routing tier to prevent quality degradation during multi-turn complex tasks. Applied on **both** the rule path and the LLM-judge path: a Phase-2 verdict (fresh or cached) is smoothed identically to a rule result, so a short ambiguous follow-up cannot downgrade an ongoing complex task.
- **LLM judge**: Phase 2 classifies ambiguous cases via a filter LLM with a bounded timeout (`_JUDGE_TIMEOUT_S`) — a hung judge call degrades to STANDARD instead of blocking routing. Callers create the judge with deterministic low temperature (0.0) to keep classification stable.
- **Min-tier floor**: `route_task(min_tier=...)` enforces a minimum tier regardless of classification result. Used by callers for complaint-up escalation (regenerate → automatic tier upgrade).
- **Penalty feedback**: `record_misroute(tier)` records misrouted tiers so PenaltyTracker reduces future misrouting probability (24h decay).
- **Cache-friendly**: Routing runs before Agent creation, so it does not affect system prompt cache hit rates.
- **Extensible**: All routers accept custom keyword sets and configuration overrides via function parameters.
- **LLM proxy**: Cursor/Codex raw LLM passthrough is out of scope — `/v1` is Agent API only.
