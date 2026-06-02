# automation/

## Overview
Automation toolkit — rule-based agent task automation. Provides CRUD operations for automation rules as LangChain tools.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Automation toolkit public API. | — |
| automation_agent_tools.py | Core | Agent-callable tools for automation rule management. | ✅ |
| protocols.py | Core | AutomationStore protocol — storage interface for automation rules. | ✅ |
| stores.py | Core | In-memory and local file implementations of AutomationStore. | ✅ |
| types.py | Config | Automation rule data models. | ✅ |

## Key Dependencies

- `utils` (files)
