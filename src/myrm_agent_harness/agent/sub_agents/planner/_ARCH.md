# planner/

## Overview

Planner Sub-agent Module — independent task planning sub-agent with multimodal input support and historical plan recall (Workflow RAG).

Session plans persist under **chat workspace** `{workspace_root}/planner/` (shadow sync: `plan.json`, `task_plan.md`, `plan_summary.txt`). Same path is read by `CompletionGuard` and resume logic. Mutually exclusive with `execution_checklist/` (Path B).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Planner Sub-agent Module | — |
| agent.py | Core | Planner Agent — independent task planning sub-agent. Accepts text or multimodal (text+image) task descriptions with optional historical plan references. | ✅ |
| archive.py | Core | Plan Archive & Recall — SQLite+Qdrant dual persistence for historical plans; vector recall as few-shot for cold-start mitigation. | ✅ |
| config.py | Config | Planner configuration and skill summary models. | ✅ |
| planner_agent_tools.py | Core | LangChain Tool wrapper — exposes PlannerAgent to the main Agent. Passes `workspace_root` into `PlannerStorage`. Handles archive triggering and recall injection. | ✅ |
| prompts.py | Core | Planner system prompts. | ✅ |
| schemas.py | Config | Planner schema definitions (Plan, PlanStep, ErrorRecord). | ✅ |
| storage.py | Core | Planner storage — workspace shadow sync (SSOT for guard/resume); `StorageProvider` fallback when no workspace root (tests). Exports `read_plan_sync_from_workspace`, `plan_exists_sync`, `save_plan_files_to_workspace`. | ✅ |

## Bind conditions

- `enable_planning=True`, or resume when `{workspace}/planner/plan.json` exists
- Excluded when Goal session uses Goal planner; excluded when execution checklist is active

## Key Dependencies

- `toolkits.storage` (StorageProvider protocol — fallback only)
- `agent.middlewares._session_context` (workspace root for tool bind)
- `toolkits.memory.protocols.vector` (VectorStoreProtocol, VectorDocument — for plan archive vector search)
- `toolkits.memory.protocols.embedding` (EmbeddingProtocol — for plan embedding)
