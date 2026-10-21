# signals/

## Overview

Orchestration control-plane JSON schemas bound via `llm.bind_tools()` and intercepted by Python orchestrators. **Not Action Tools** — excluded from `_TOOL_LAYERS`, `ToolRegistry`, and default GeneralAgent Turn1 bind.

Parent: [../_ARCH.md](../_ARCH.md)

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Core | Re-exports signal names, DR tool builders, verifier factory | ✅ |
| catalog.py | Core | `ORCHESTRATION_SIGNAL_NAMES` SSOT (DR + Verifier) | ✅ |
| deep_research.py | Core | DR `dispatch_research` / `think` / `finalize_report` schemas + `build_orchestrator_tools` | ✅ |
| verifier.py | Core | Verifier `submit_verdict` session factory | ✅ |

## Key Dependencies

- `agent/orchestration/` — consumed by orchestrators; never registered as Action Tools
