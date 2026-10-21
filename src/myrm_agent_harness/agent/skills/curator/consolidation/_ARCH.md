# consolidation/

## Overview
Skill consolidation (umbrella merge). Detects fragmented skill clusters and merges them into class-level umbrella skills.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports orchestrator and consolidation types | — |
| types.py | Core | SkillCluster, ConsolidationAction, ConsolidationPlan, ConsolidationReport, `occupied_names` | ✅ |
| cluster_detector.py | Core | Hybrid prefix + embedding-based cluster detection | ✅ |
| judge.py | Core | LLM structured-output judge for merge strategy; drops actions aimed at a taken umbrella name or an unknown target | ✅ |
| executor.py | Core | Applies MERGE/CREATE_UMBRELLA/DEMOTE actions; archives sources only after their content landed | ✅ |
| orchestrator.py | Core | SkillConsolidator pipeline: detect → judge → execute (dry-run support) | ✅ |

## Untrusted targets

The LLM proposes every target name, so no name in a plan is trusted.

- `occupied_names(skills, reserved_names)` (types.py) is the set of case-folded names a new umbrella must not take: every skill the run may modify plus `reserved_names`, the skills the host keeps out of the run (the curator passes its protected and installed skills). Case is folded because a case-insensitive file system maps names that differ only in case to one skill directory.
- The judge drops a CREATE_UMBRELLA whose name is occupied and a MERGE/DEMOTE whose target is not one of the skills the run may modify, and logs a warning. The dropped cluster is left as it is, like KEEP, so the preview never promises what the executor would refuse.
- The executor enforces the same at the side-effect boundary: it never saves an umbrella over an occupied name, and a MERGE/DEMOTE only writes into a candidate. The write backend reports a refused support-file write by returning a failure, so the executor checks the result and fails the action before it archives any source; support files already written stay in the target.

## Module Dependencies

- `backends.skills.creation_protocols` (SkillWriteBackend)
- `toolkits.retriever.embedding.base` (EmbeddingService)
- `langchain_core.language_models` (BaseChatModel)
