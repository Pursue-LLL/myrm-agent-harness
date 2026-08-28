# sub_agents/

## Overview
Sub-agent subsystem — lifecycle management and configuration loading.

Detailed design: [SUB_AGENT_SYSTEM.md](SUB_AGENT_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Sub-agent subsystem — lifecycle management and configuration loading. | — |
| branch_scoped_compaction.py | Core | Branch-scoped subagent artifact and structured summary compaction merger. Collects child trackers, extracts modified files, and enriches parent summaries. | ✅ |
| budget.py | Core | Delegation budget guard. Tracks descendant spawn count for one root run. | ✅ |
| builder.py | Core | Subagent construction helpers — tool filtering via DelegationCapabilityManifest + delegation_policy, model resolution, token merge. | ✅ |
| checkpointer.py | Core | Shared in-memory checkpointer singleton (`get_subagent_checkpointer`, `delete_subagent_checkpoint`) for subagent HITL approval thread isolation. | ✅ |
| delegation_policy.py | Core | Server-extensible L1 leaf blocklist (`register_leaf_blocked_tools`). | ✅ |
| hitl_tool_policy.py | Core | Import-safe HITL tool policy SSOT (`HitlToolPolicy`, `HITL_TOOL_POLICY`) used by `types.py` for leaf blocking. | ✅ |
| config_loader.py | Config | External config loader. YAML validation (Pydantic + Action Tool SSOT + regex tool names). | ✅ |
| event_forwarder.py | Core | Subagent event forwarder. Translates subagent events into progress and log events. Includes staleness detection (`is_stale`, `_check_and_emit_stale`) with configurable thresholds and in-tool multiplier. `internal=True` silences all emissions (internal verification nodes stay off user-facing surfaces). | ✅ |
| executor.py | Core | SubagentExecutor aggregate root (mixin MRO: Retry → Attempt → Delegation). Re-exports helper functions for tests and notifications. | ✅ |
| executor_retry_mixin.py | Internal | Retry loop, workspace isolation (immediate sync_back → `apply_isolated_sync_back_with_snapshots` before return; merge fail → merge_warning + result metadata), hooks, graceful cancellation (`run_with_retry`). | ✅ |
| executor_attempt_mixin.py | Internal | Single child-agent attempt: fork context, event forwarding, handover parsing, taint propagation (`_inherit_parent_context`, `_run_single_attempt`). | ✅ |
| executor_delegation_mixin.py | Internal | Orchestrator-role delegation meta-tool attachment (`_attach_child_delegation_tools`). | ✅ |
| executor_helpers.py | Internal | Pure helpers: fork filter, error compaction, `_auto_vault_or_truncate` (vault + inline artifact + file_read hint), handover parse (via `parse_llm_json_object`, robust against fences/prose/trailing commas), cascade cancel. | ✅ |
| manager.py | Core | Subagent lifecycle manager. Core state tracking, validation, cleanup, capacity, and observability. Inherits spawn/execution from `_manager_spawn` and control operations from `_manager_control`. Maintains strong global registry `COMPLETED_SUBAGENT_RESULTS` (TTL 1h / 1000 FIFO) so terminal results survive after the parent gateway session ends. | ✅ |
| _manager_spawn.py | Internal | Spawn and execution mixin for SubagentManager (`_run_subagent*`, `spawn_child`). `spawn_child` accepts `internal: bool` — internal nodes are hidden from SSE/global events, teammate registration, and the shared notification queue. No wall-clock timeout by default; hard timeout only when `timeout_seconds` is explicitly set. | ✅ |
| _manager_control.py | Internal | Control plane mixin for SubagentManager (`cancel_child`, `steer_child`, `list_children`, `wait_children`, `drain_notifications`, `run_alternatives`, `run_chain`, `run_council`, `run_with_verification`). `list_children` filters out `internal` nodes (running and completed) so user-facing trees only show business tasks. | ✅ |
| session_tree.py | Core | Merge gateway + ACTIVE_SUBAGENTS rows (incl. strong `COMPLETED_SUBAGENT_RESULTS` terminal history); match REST uuid against `chat_` / `chat_chat_` session ids; registry cancel-all helper. | ✅ |
| notifications.py | Core | Push-based notification formatting for subagent completion events and active subagent context injection. | ✅ |
| SUBAGENT_NOTIFICATION_STRATEGY.md | L2 | Cache-safe subagent notification delivery (SSE + wakeup user message) | — |
| orchestrator.py | Core | Subagent composition patterns — chain, batch, alternatives (text compare; deferred isolated workspaces discarded), council, and DAG execution (with Declarative Dependency Context Filtering, Auto-Vaulting, Swarm Fission yield-resume, Optional Path Guard via `allow_failure` on PlanStep, and `run_council` for multi-expert cross-review). Delegates verification to `_orchestrator_verification` and council to `_orchestrator_council`. | ✅ |
| spawn_prep.py | Core | Shared spawn prep SSOT (coerce_spawn_readonly floor, readonly, isolation, sanitize store via merge_metadata). | ✅ |
| _orchestrator_council.py | Internal | Council orchestration — multi-expert parallel analysis with cross-review debate and chair synthesis, COUNCIL_PHASE event emission. | ✅ |
| _orchestrator_verification.py | Internal | Adversarial verification retry loop (`run_with_verification`). Supports standard single verifier, `auditor_blind` (worker self-praising narrative stripping + workspace mutation self-healing revert), and `multi_skeptic` (parallel 3-skeptic majority voting with Fail-Closed protection). Accepts a business `task_id`: the first worker runs under that visible id (`internal=False`) while retry workers and verifiers spawn as internal nodes; the final outcome is mirrored onto the business `SubAgentResult`. Delegates single-round verifier spawn to `_verifier_round.py`. | ✅ |
| _verifier_round.py | Internal | Single-round verifier spawn (always `internal=True`), workspace mutation detection & self-healing rollback (`revert_workspace_mutations`), and `verify_worker_output()` (Cron post-run and delegate paths). | ✅ |
| _verification_parsing.py | Internal | `VerificationVerdict` parsing + VERIFICATION_VERDICT SSE emission. Parses the verifier verdict via `parse_llm_json_object(require_key="verdict")` (robust against fences, prose, bare control chars, trailing commas). | ✅ |
| _workspace_diff.py | Internal | Lightweight stat-based workspace file change detection (`take_workspace_snapshot`, `format_workspace_diff`) and self-healing rollback (`revert_workspace_mutations`) for verifier isolation. | ✅ |
| prompts.py | Core | Default prompt templates for multi-agent coordination. | ✅ |
| registry.py | Core | Subagent configuration registry and loader. Provides global config registration and lookup. | ✅ |
| types.py | Config | Subagent subsystem core type definitions. Defines all subagent-related data types, enums, protocols, DelegationCapabilityManifest, SubagentConfig (including `timeout_seconds: int | None = None` — no wall-clock timeout by default, `__post_init__` normalizes ≤0→None and enforces min 30s floor; `max_error_chars` for error compaction control; `stale_after_seconds`/`in_tool_stale_multiplier`/`stale_auto_cancel` for staleness detection), CouncilOpinion, CouncilResult, VerificationSummary, and SubAgentResult.verification. `SubAgentResult.internal` marks framework-internal nodes (verification workers/verifiers) hidden from user-facing trees. | ✅ |
| workspace_isolation.py | Core | Workspace isolation for subagent execution. COW clone with ignore-pattern filtering (node_modules, .git, dist, etc.), max_bytes safety guard, and efficient file counting. | ✅ |

**Tests mocking executor internals** must patch the defining module (e.g. `executor_attempt_mixin.build_child_agent`), not the aggregate `executor` module.

| Submodule | Description |
|-----------|-------------|
| checkpoint/ | Subagent checkpoint utilities package. Includes orphan recovery for automatic resumption after restart. |
| dag_plan.py | DAG `Plan`/`PlanStep` schemas for orchestrator only (not user-facing progress) |

## Key Dependencies

- `utils`
