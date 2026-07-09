# deep_research/

## Overview
Public API for the Deep Research system. Import everything from here.

Detailed design: [DEEP_RESEARCH_SYSTEM.md](DEEP_RESEARCH_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API for the Deep Research system. Import everything from here. | ✅ |
| config.py | Config | Configuration and type definitions for the Deep Research system. | ✅ |
| helpers.py | Core | Stateless helper functions for orchestrator phases and cost estimation | ✅ |
| orchestrator.py | Core | Multi-phase orchestrator event loop; composes plan/research + phase mixins | ✅ |
| _orchestrator_phases.py | Internal | Clarification, research dispatch, and report generation mixin | ✅ |
| _orchestrator_plan_research.py | Internal | Plan + research-loop phase mixin (`_phase_plan`, `_phase_research`) | ✅ |
| prompts.py | Core | All prompt templates for the Deep Research system. | ✅ |

Orchestration signal schemas: `../orchestration/signals/deep_research.py` (not Action Tools).

## Key Dependencies

- `utils`
- `agent/meta_tools/clarification`
- `agent/orchestration/signals/deep_research`
