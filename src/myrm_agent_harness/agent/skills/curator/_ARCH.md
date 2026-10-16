# curator/

## Overview
Skill Curator — automated lifecycle governance for agent-created skills.
Performs stateless sweeps: evaluates skills against CuratorConfig thresholds, applies stale/archive transitions, and optionally runs consolidation (umbrella merge) to reduce skill fragmentation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports SkillCurator, CuratorRunResult, CuratorTransition. | — |
| anti_sycophancy_adversarial_engine.py | Core | Detects sycophantic alignment traps and generates adversarial critique exemplars. | ✅ |
| anti_sycophancy_types.py | Types | Types and models for anti sycophancy. | ✅ |
| engine.py | Core | SkillCurator: stateless curator engine that orchestrates lifecycle sweeps + LRU eviction + consolidation; skills named in `protected_names` are exempt from all of it. | ✅ |
| self_dismantling_curator_engine.py | Core | Performs self-distillation sweeps over memory and skill artifacts. | ✅ |
| types.py | Core | CuratorTransition, CuratorRunResult data types. | ✅ |

| Submodule | Description |
|-----------|-------------|
| consolidation/ | Skill consolidation (umbrella merge). See [consolidation/_ARCH.md](consolidation/_ARCH.md). |

## Key Dependencies

- `backends.skills.curator_config` (CuratorConfig)
- `backends.skills.forgetting_strategy` (DefaultForgettingStrategy)
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

## Protected skills

`run` / `run_async` take `protected_names`: skills the host depends on (e.g. bound by a scheduled job or an agent profile). A protected skill is never staled, archived, LRU-evicted or consolidated, and — like a pinned one — does not count toward `max_skills`. It is tallied in `CuratorRunResult.skipped_protected`; a pinned skill is tallied as `skipped_pinned` even when also protected. The harness stays ignorant of what binds a skill; the host decides.

`installed_names` carries the same kind of host knowledge: skills the host knows were installed rather than authored (a registry install, another tool's skill folder). They are exempt exactly like `protected_names`, but only while `CuratorConfig.protect_installed_skills` is on; switching it off hands them back to the normal lifecycle. The engine never inspects `SkillMetadata.trust` for this: a local scan stamps every skill `TRUSTED`, so trust says nothing about provenance.

## Configuration

`CuratorConfig` validates its numeric fields on construction (a sweep runs unattended, so a zero-day stale window or a zero skill limit would make every eligible skill due in one pass) and raises `ValueError` outside the safe ranges.

All consolidation parameters are in `CuratorConfig`:
- `consolidation_enabled`: Master switch (default: **False** — LLM consolidation is opt-in via Settings)
- `protect_installed_skills`: Exempt the skills the host passes as `installed_names` from auto transitions (default: True)
- `protect_system_skills`: Exempt prebuilt skills (`/prebuilt/` path) from auto transitions (default: True)
- `consolidation_min_skills`: Minimum active skills to trigger (default: 10)
- `consolidation_min_cluster_size`: Minimum cluster members (default: 3)
- `consolidation_similarity_threshold`: Embedding cosine threshold (default: 0.75)
