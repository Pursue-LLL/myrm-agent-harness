# consolidation/

## Overview
Skill consolidation (umbrella merge). Detects fragmented skill clusters and merges them into class-level umbrella skills.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports orchestrator and consolidation types | — |
| types.py | Core | SkillCluster, ConsolidationAction, ConsolidationPlan, ConsolidationReport | ✅ |
| cluster_detector.py | Core | Hybrid prefix + embedding-based cluster detection | ✅ |
| judge.py | Core | LLM structured-output judge for merge strategy | ✅ |
| executor.py | Core | Applies MERGE/CREATE_UMBRELLA/DEMOTE actions; archives sources | ✅ |
| orchestrator.py | Core | SkillConsolidator pipeline: detect → judge → execute (dry-run support) | ✅ |

## Module Dependencies

- `backends.skills.creation_protocols` (SkillWriteBackend)
- `toolkits.retriever.embedding.base` (EmbeddingService)
- `langchain_core.language_models` (BaseChatModel)
