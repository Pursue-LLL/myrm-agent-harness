# sub_agents/

## Overview
Sub-agent subsystem — lifecycle management and configuration loading.

Detailed design: [SUB_AGENT_SYSTEM.md](SUB_AGENT_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Sub-agent subsystem — lifecycle management and configuration loading. | — |
| budget.py | Core | Delegation budget guard. Tracks descendant spawn count for one root run. | ✅ |
| builder.py | Core | Subagent construction helpers — tool filtering via DelegationCapabilityManifest, model resolution, token merge. | ✅ |
| config_loader.py | Config | External config loader. Loads subagent configurations from YAML files with strict validation. | ✅ |
| event_forwarder.py | Core | Subagent event forwarder. Translates subagent events into progress and log events. | ✅ |
| executor.py | Core | Subagent executor. Runs child agents with retry, workspace isolation, event handling, cascade cancellation, manifest-scoped delegation tools, taint propagation with inbound security warnings, approval deadlock protection, error compaction (`_compact_error_message` — head+marker+tail truncation prevents context pollution), and conclusion-oriented fork context filtering (`_filter_fork_messages` + `max_fork_tokens` truncation). | ✅ |
| manager.py | Core | Subagent lifecycle manager. Core state tracking, validation, cleanup, capacity, and observability. Inherits spawn/execution from `_manager_spawn` and control operations from `_manager_control`. | ✅ |
| _manager_spawn.py | Internal | Spawn and execution mixin for SubagentManager (`_run_subagent*`, `spawn_child`). | ✅ |
| _manager_control.py | Internal | Control plane mixin for SubagentManager (`cancel_child`, `steer_child`, `list_children`, `wait_children`, `drain_notifications`, `run_chain`, `run_with_verification`). | ✅ |
| notifications.py | Core | Push-based notification formatting for subagent completion events and active subagent context injection. | ✅ |
| orchestrator.py | Core | Subagent composition patterns — chain, batch, and DAG execution (with Declarative Dependency Context Filtering, Auto-Vaulting, and Swarm Fission yield-resume). Delegates verification to `_orchestrator_verification`. | ✅ |
| _orchestrator_verification.py | Internal | Adversarial verification orchestration — Worker -> Verifier -> Retry loop with structured verdict parsing and ReadonlyExecutorProxy sandboxing. | ✅ |
| prompts.py | Core | Default prompt templates for multi-agent coordination. | ✅ |
| registry.py | Core | Subagent configuration registry and loader. Provides global config registration and lookup. | ✅ |
| types.py | Config | Subagent subsystem core type definitions. Defines all subagent-related data types, enums, protocols, DelegationCapabilityManifest, and SubagentConfig (including `max_error_chars` for error compaction control). | ✅ |
| workspace_isolation.py | Core | Workspace isolation for subagent execution. COW clone with ignore-pattern filtering (node_modules, .git, dist, etc.), max_bytes safety guard, and efficient file counting. | ✅ |

| Submodule | Description |
|-----------|-------------|
| checkpoint/ | Subagent checkpoint utilities package. Includes orphan recovery for automatic resumption after restart. |
| planner/ | Planner Sub-agent Module |

## Key Dependencies

- `utils`
