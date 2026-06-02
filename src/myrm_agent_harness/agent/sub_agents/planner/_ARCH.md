# planner/

## Overview
Planner Sub-agent Module

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Planner Sub-agent Module | — |
| agent.py | Core | Planner Agent — independent task planning sub-agent. | ✅ |
| config.py | Config | Planner configuration and skill summary models. | ✅ |
| planner_agent_tools.py | Core | LangChain Tool wrapper — exposes PlannerAgent to the main Agent. | ✅ |
| prompts.py | Core | Planner system prompts. | ✅ |
| schemas.py | Config | Planner schema definitions (Plan, PlanStep, ErrorRecord). | ✅ |
| storage.py | Core | Planner storage adapter. | ✅ |

## Key Dependencies

- `toolkits.storage` (StorageProvider protocol)
