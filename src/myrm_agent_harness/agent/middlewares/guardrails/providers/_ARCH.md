# providers/

## Overview
Concrete `GuardrailProvider` implementations for the guardrails middleware chain.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| skill_boundary.py | Core | SkillBoundaryProvider — parameter-aware skill permission enforcement (supports sync/async permission checkers; async path awaits async checkers, sync path wraps them via `asyncio.run`) | — |

## Module Dependencies

- `agent.middlewares.guardrails.core::GuardrailProvider` (POS: guardrail provider protocol)
