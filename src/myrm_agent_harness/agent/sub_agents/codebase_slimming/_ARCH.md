# codebase_slimming/

## Overview
Agentic codebase slimming subsystem — dead-code topology scanning, equivalence-guarded refactor execution, and a resumable multi-module task ledger.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for the slimming pipeline, scanner, guard, and data models. | ✅ |
| types.py | Core | Data models: `DeadCodeCandidate`, `DeadCodeScanReport`, `SlimmingLedger`, `SlimmingModuleTask`, `SlimmingRiskLevel`, `SlimmingTaskStatus`, `EquivalenceVerdict`. | ✅ |
| scanner.py | Core | Dead code and redundant topology scanner for Python codebases (`DeadCodeTopologyScanner`). | ✅ |
| guard.py | Core | Behavior invariance assertion and regression guard for slimming refactors (`EquivalenceInvarianceGuard`). | ✅ |
| pipeline.py | Core | `CodebaseSlimmingPipeline` — coordinates concurrent subagents across module tasks with ledger-backed resumption. | ✅ |

## Key Dependencies

- `agent/sub_agents/workspace_isolation` (isolated workspace execution)
- `agent/sub_agents/codebase_slimming` (intra-package: guard, scanner, types)
- `utils/logger_utils` (agent logger)
