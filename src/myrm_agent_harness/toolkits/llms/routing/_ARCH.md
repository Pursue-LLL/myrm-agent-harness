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

- **Momentum**: `complexity_router` supports session momentum — short follow-up messages inherit the conversation's recent routing tier to prevent quality degradation during multi-turn complex tasks.
- **Cache-friendly**: Routing runs before Agent creation, so it does not affect system prompt cache hit rates.
- **Extensible**: All routers accept custom keyword sets and configuration overrides via function parameters.
