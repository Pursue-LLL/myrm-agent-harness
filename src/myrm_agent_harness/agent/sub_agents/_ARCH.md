# sub_agents/

## Overview
Sub-agent subsystem — lifecycle management and configuration loading.

Detailed design: [SUB_AGENT_SYSTEM.md](SUB_AGENT_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Sub-agent subsystem — lifecycle management and configuration loading. | — |
| budget.py | Core | Delegation budget guard. Tracks descendant spawn count for one root run. | ✅ |
| builder.py | Core | Subagent construction helpers — tool filtering via DelegationCapabilityManifest + delegation_policy, model resolution, token merge. | ✅ |
| delegation_policy.py | Core | Server-extensible L1 leaf blocklist (`register_leaf_blocked_tools`). | ✅ |
| config_loader.py | Config | External config loader. YAML validation (Pydantic + Action Tool SSOT + regex tool names). | ✅ |
| event_forwarder.py | Core | Subagent event forwarder. Translates subagent events into progress and log events. Includes staleness detection (`is_stale`, `_check_and_emit_stale`) with configurable thresholds and in-tool multiplier. | ✅ |
| executor.py | Core | SubagentExecutor aggregate root (mixin MRO: Retry → Attempt → Delegation). Re-exports helper functions for tests and notifications. | ✅ |
| executor_retry_mixin.py | Internal | Retry loop, workspace isolation, hooks, and graceful cancellation (`run_with_retry`). | ✅ |
| executor_attempt_mixin.py | Internal | Single child-agent attempt: fork context, event forwarding, handover parsing, taint propagation (`_inherit_parent_context`, `_run_single_attempt`). | ✅ |
| executor_delegation_mixin.py | Internal | Orchestrator-role delegation meta-tool attachment (`_attach_child_delegation_tools`). | ✅ |
| executor_helpers.py | Internal | Pure helpers: fork filter, error compaction, `_auto_vault_or_truncate` (vault + inline artifact + file_read hint), handover parse, cascade cancel. | ✅ |
| manager.py | Core | Subagent lifecycle manager. Core state tracking, validation, cleanup, capacity, and observability. Inherits spawn/execution from `_manager_spawn` and control operations from `_manager_control`. | ✅ |
| _manager_spawn.py | Internal | Spawn and execution mixin for SubagentManager (`_run_subagent*`, `spawn_child`). | ✅ |
| _manager_control.py | Internal | Control plane mixin for SubagentManager (`cancel_child`, `steer_child`, `list_children`, `wait_children`, `drain_notifications`, `run_alternatives`, `run_chain`, `run_council`, `run_with_verification`). | ✅ |
| session_tree.py | Core | Merge gateway + ACTIVE_SUBAGENTS rows; match REST uuid against `chat_` / `chat_chat_` session ids; registry cancel-all helper. | ✅ |
| notifications.py | Core | Push-based notification formatting for subagent completion events and active subagent context injection. | ✅ |
| SUBAGENT_NOTIFICATION_STRATEGY.md | L2 | Cache-safe subagent notification delivery (SSE + wakeup user message) | — |
| orchestrator.py | Core | Subagent composition patterns — chain, batch, alternatives, council, and DAG execution (with Declarative Dependency Context Filtering, Auto-Vaulting, Swarm Fission yield-resume, Optional Path Guard via `allow_failure` on PlanStep, `run_alternatives` for parallel multi-solution generation with deferred workspace merge, and `run_council` for multi-expert cross-review). Delegates verification to `_orchestrator_verification` and council to `_orchestrator_council`. | ✅ |
| _orchestrator_council.py | Internal | Council orchestration — multi-expert parallel analysis with cross-review debate and chair synthesis, COUNCIL_PHASE event emission. | ✅ |
| _orchestrator_verification.py | Internal | Adversarial verification retry loop (`run_with_verification`). Delegates single-round verifier spawn to `_verifier_round.py`. | ✅ |
| _verifier_round.py | Internal | Single-round verifier spawn + `verify_worker_output()` (Cron post-run and delegate paths). | ✅ |
| _verification_parsing.py | Internal | `VerificationVerdict` parsing + VERIFICATION_VERDICT SSE emission. | ✅ |
| _workspace_diff.py | Internal | Lightweight stat-based workspace file change detection for adversarial verification diff injection. | ✅ |
| prompts.py | Core | Default prompt templates for multi-agent coordination. | ✅ |
| registry.py | Core | Subagent configuration registry and loader. Provides global config registration and lookup. | ✅ |
| types.py | Config | Subagent subsystem core type definitions. Defines all subagent-related data types, enums, protocols, DelegationCapabilityManifest, SubagentConfig (including `max_error_chars` for error compaction control, `stale_after_seconds`/`in_tool_stale_multiplier`/`stale_auto_cancel` for staleness detection), CouncilOpinion, and CouncilResult. | ✅ |
| workspace_isolation.py | Core | Workspace isolation for subagent execution. COW clone with ignore-pattern filtering (node_modules, .git, dist, etc.), max_bytes safety guard, and efficient file counting. | ✅ |

**Tests mocking executor internals** must patch the defining module (e.g. `executor_attempt_mixin.build_child_agent`), not the aggregate `executor` module.

| Submodule | Description |
|-----------|-------------|
| checkpoint/ | Subagent checkpoint utilities package. Includes orphan recovery for automatic resumption after restart. |
| dag_plan.py | DAG `Plan`/`PlanStep` schemas for orchestrator only (not user-facing progress) |

## Key Dependencies

- `utils`
