# curator/

## Overview
Skill Curator — automated lifecycle governance for agent-created skills.
Performs stateless sweeps: evaluates skills against CuratorConfig thresholds, applies stale/archive transitions, and optionally runs consolidation (umbrella merge) to reduce skill fragmentation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports SkillCurator, CuratorRunResult, CuratorTransition. | — |
| engine.py | Core | SkillCurator: stateless curator engine that orchestrates lifecycle sweeps + LRU eviction + consolidation. | ✅ |
| types.py | Core | CuratorTransition, CuratorRunResult data types. | ✅ |

| Submodule | Description |
|-----------|-------------|
| consolidation/ | Skill consolidation (umbrella merge). See [consolidation/_ARCH.md](consolidation/_ARCH.md). |

## Key Dependencies

- `backends.skills.forgetting_strategy` (CuratorConfig, DefaultForgettingStrategy)
- `backends.skills.stats_collector` (SkillStatsCollector)
- `backends.skills.types` (SkillMetadata, SkillLifecycleStatus)
- `backends.skills.creation_protocols` (SkillWriteBackend — for consolidation execution)
- `toolkits.retriever.embedding.base` (EmbeddingService — for cluster detection)
- `langchain_core.language_models` (BaseChatModel — for LLM judge)

## Pipeline Flow

```
Skills → Filter (eligible) → ClusterDetector (prefix + embedding)
       → ConsolidationJudge (LLM) → ConsolidationPlan
       → [dry_run?] → ConsolidationExecutor → ConsolidationReport
```

## Configuration

All consolidation parameters are in `CuratorConfig`:
- `consolidation_enabled`: Master switch (default: True)
- `consolidation_min_skills`: Minimum active skills to trigger (default: 10)
- `consolidation_min_cluster_size`: Minimum cluster members (default: 3)
- `consolidation_similarity_threshold`: Embedding cosine threshold (default: 0.75)
