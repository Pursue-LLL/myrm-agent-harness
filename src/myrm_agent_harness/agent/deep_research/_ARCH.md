# deep_research/

## Overview
Public API for the Deep Research system. Import everything from here.

Detailed design: [DEEP_RESEARCH_SYSTEM.md](DEEP_RESEARCH_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API for the Deep Research system. Import everything from here. | ✅ |
| config.py | Config | Configuration and type definitions for the Deep Research system. | ✅ |
| helpers.py | Core | Stateless helper functions extracted from orchestrator.py to keep | ✅ |
| orchestrator.py | Core | Multi-phase orchestrator for Deep Research; drives the main event loop, planning, and parallel research. Inherits clarification/report phases from `_orchestrator_phases`. | ✅ |
| _orchestrator_phases.py | Internal | Phase implementation mixin — clarification, research agent dispatch, and report generation. | ✅ |
| prompts.py | Core | All prompt templates for the Deep Research system. | ✅ |
| tools.py | Core | Defines the 3 fake/meta tools injected into the orchestrator LLM context. | ✅ |

## Key Dependencies

- `utils`
- `agent/meta_tools/clarification`
