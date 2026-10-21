# deep_research/

## Overview
Public API for the Deep Research system. Import everything from here.

Detailed design: [DEEP_RESEARCH_SYSTEM.md](DEEP_RESEARCH_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API for the Deep Research system. Import everything from here. | ✅ |
| config.py | Config | Configuration and type definitions (`DeepResearchPhase`: CLARIFY→PLAN→EXPLORE→RESEARCH→REPORT) | ✅ |
| helpers.py | Core | Stateless helper functions for orchestrator phases and cost estimation | ✅ |
| orchestrator.py | Core | Multi-phase orchestrator event loop; composes plan/research + phase mixins | ✅ |
| _orchestrator_phases.py | Internal | Clarification (`CLARIFICATION_REQUIRED` + `MESSAGE`), research dispatch, and report generation mixin | ✅ |
| _orchestrator_plan_research.py | Internal | Plan + research-loop phase mixin (`_phase_plan`, `_phase_research`) | ✅ |
| prompts.py | Core | All prompt templates for the Deep Research system | ✅ |

Orchestration signal schemas: `../orchestration/signals/deep_research.py` (not Action Tools).

## Key Dependencies

- `utils`
- `agent/meta_tools/clarification`
- `agent/orchestration/signals/deep_research`

## Lifecycle Phases

```
CLARIFY → PLAN → EXPLORE → RESEARCH (cycles) → REPORT
```

- **CLARIFY**: Optional HITL clarification with the user (`CLARIFICATION_REQUIRED` SSE with structured form + question `MESSAGE`)
- **PLAN**: LLM generates a structured research plan
- **EXPLORE**: Optional zero-cost local knowledge pre-query via `on_explore` callback. Injects `local_context` into the orchestrator system prompt to avoid redundant web searches
- **RESEARCH**: Orchestrator loop dispatching sub-agents for web research
- **REPORT**: Final report generation from accumulated research

## Callback System

| Callback | Phase | Purpose |
|----------|-------|---------|
| `on_clarify` | CLARIFY | Suspend for user clarification input |
| `on_plan_ready` | PLAN | Suspend for user plan review/edit |
| `on_explore` | EXPLORE | Query local knowledge (Wiki FTS5), zero LLM cost |
| `on_cycle_complete` | RESEARCH | Per-cycle feedback/guidance injection |
| `on_report_ready` | REPORT | Post-report actions (e.g., wiki vault) |
