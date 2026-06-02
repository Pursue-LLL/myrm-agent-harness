# agent/

## Overview
Agent core module — public API.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent core module — public API. | — |
| base_agent.py | Core | Base Agent — lightweight agent with streaming, token tracking, and artifacts. | ✅ |
| skill_agent.py | Core | Skill Agent class — extends BaseAgent with skill system, hooks, and session lifecycle. | ✅ |
| _skill_agent_context.py | Internal | ContextVar management and background task utilities for SkillAgent. | ✅ |
| _skill_agent_review.py | Internal | SkillAgent session-end review mixin — skill review, wiki archive, recurrence detection. | ✅ |
| _skill_agent_tools.py | Internal | SkillAgent tool building mixin — meta-tools, planner, wiki tools assembly. | ✅ |
| skill_agent_factory.py | Core | Agent factory function. Provides create_skill_agent() to simplify Agent creation. | ✅ |
| types.py | Config | Agent core runtime type definitions. AgentRuntimeSpec (incl. tool_groups for skill conditional activation), AgentRuntimeConfig, EngineParams, completion status, run statistics, etc. | ✅ |

| Submodule | Description |
|-----------|-------------|
| _internals/ | Agent internal helpers — private implementation details for agent core files. |
| acp/ | Agent Communication Protocol integration — default factory for standalone ACP server usage. |
| artifacts/ | Artifacts system — artifact lifecycle management. |
| background_worker/ | Background worker module for agent. |
| config/ | Agent configuration package — unified export of all config types and utilities. |
| context_management/ | Context management module. |
| coordination/ | Subagent P2P mailbox — session-scoped in-memory queues with optional JSONL persistence for sibling subagent direct messaging. |
| deep_research/ | Public API for the Deep Research system. |
| errors/ | Agent execution errors with unified diagnostics. |
| event_log/ | Complements Checkpointer with full event history. |
| extensions/ | Extensions submodule. |
| file_snapshot/ | Workspace file versioning and rollback — transparent file-level snapshots before file-mutating operations. |
| goals/ | Goal-based autonomous loop engine — long-running objectives with 4-dimension budget control, semantic completion auditing, and priority queueing. |
| hooks/ | User-configurable lifecycle hook system. Complements middlewares (framework-internal safety logic). |
| meta_tools/ | Agent meta-tools module. Provides tools that depend on Agent framework infrastructure (Bash, File Ops, etc.). |
| middlewares/ | Agent middleware system exports. Complete middleware stack (context management, debug logging, security, etc.). |
| observability/ | Framework-level observability layer. Business layer subscribes to EventBus. |
| parallel/ | Parallel task execution — shared spawn path for batch_delegate_tasks_tool and Swarm Fission with semaphore-based concurrency. |
| security/ | Agent security subsystem — 6-layer onion defense architecture. |
| skills/ | Skills runtime — skill execution and management. |
| streaming/ | BaseAgent event processing pipeline. |
| sub_agents/ | Sub-agent subsystem — lifecycle management and configuration loading. |
| tool_management/ | Tool management subsystem — unified tool registration, dedup, ordering, and lifecycle. |
| workspace_rules/ | Workspace rules — project-level context file discovery and injection. Two-layer: startup middleware injection + progressive subdirectory discovery via tool interception. |

## Key Dependencies

- `backends`
- `infra`
- `toolkits`
- `utils`
