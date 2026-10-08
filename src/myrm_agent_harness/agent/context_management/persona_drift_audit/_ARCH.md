# persona_drift_audit/

## Overview
Deterministic persona and long-term memory drift audit, line-by-line reality reconciliation, and human-confirmed purification subsystem. Enforces the "Read only until my yes" and "Every line earns its place" engineering principles by auditing SOUL.md, USER.md, MEMORY.md, and AGENTS.md against real workspace environments, tagging 4D bad smells (STALE, DUPLICATE, CONTRADICTORY, NO_OP), generating interactive diff plans, and executing atomic purification upon explicit confirmation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package facade exporting persona drift types, reconciler, diff engine, and suite facade. | — |
| drift_types.py | Types | Strongly typed data structures for bad-smell categories, flagged line smells, file drift audit results, diff plans, and execution outcomes. | ✅ |
| line_by_line_reconciler.py | Core | Line-by-line reality reconciliation engine scanning content against reality and tagging four dimensions of degradation. | ✅ |
| purification_diff_engine.py | Core | Read-only diff plan generator and human-confirmed purification executor enforcing the "Read only until my yes" gate. | ✅ |
| persona_drift_audit_suite.py | Facade | Unified facade suite orchestrating workspace persona file auditing, diff plan construction, and confirmed purification. | ✅ |

## Key Dependencies

- stdlib: `pathlib`, `re`, `dataclasses`, `typing`
- Internal: `myrm_agent_harness.agent.context_management`
