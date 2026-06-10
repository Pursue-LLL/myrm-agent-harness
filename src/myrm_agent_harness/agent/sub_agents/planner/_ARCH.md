# planner/

## Overview
Planner Sub-agent Module — independent task planning sub-agent with multimodal input support and historical plan recall (Workflow RAG).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Planner Sub-agent Module | — |
| agent.py | Core | Planner Agent — independent task planning sub-agent. Accepts text or multimodal (text+image) task descriptions with optional historical plan references. | ✅ |
| archive.py | Core | Plan Archive & Recall — SQLite+Qdrant dual persistence for historical plans; vector recall as few-shot for cold-start mitigation. | ✅ |
| config.py | Config | Planner configuration and skill summary models. | ✅ |
| planner_agent_tools.py | Core | LangChain Tool wrapper — exposes PlannerAgent to the main Agent. Handles archive triggering and recall injection. | ✅ |
| prompts.py | Core | Planner system prompts. | ✅ |
| schemas.py | Config | Planner schema definitions (Plan, PlanStep, ErrorRecord). | ✅ |
| storage.py | Core | Planner storage adapter (current plan persistence). | ✅ |

## Key Dependencies

- `toolkits.storage` (StorageProvider protocol)
- `toolkits.memory.protocols.vector` (VectorStoreProtocol, VectorDocument — for plan archive vector search)
- `toolkits.memory.protocols.embedding` (EmbeddingProtocol — for plan embedding)
