# agent/

## Overview

Agent core module — public API for BaseAgent / SkillAgent runtime.

**Consumer boundary (external integrators):** import `myrm_agent_harness.api` and submodules `api.hooks` / `api.skills` — **not** `agent._*` private modules. See [../api/_ARCH.md](../api/_ARCH.md).

**L2 system docs**: [sub_agents/SUB_AGENT_SYSTEM.md](sub_agents/SUB_AGENT_SYSTEM.md) · [skills/SKILL_SYSTEM.md](skills/SKILL_SYSTEM.md) · [meta_tools/META_TOOLS_SYSTEM.md](meta_tools/META_TOOLS_SYSTEM.md) · [context_management/CONTEXT_MANAGEMENT_SYSTEM.md](context_management/CONTEXT_MANAGEMENT_SYSTEM.md) · [middlewares/MIDDLEWARE_SYSTEM.md](middlewares/MIDDLEWARE_SYSTEM.md) · [streaming/STREAMING_SYSTEM.md](streaming/STREAMING_SYSTEM.md) · [event_log/EVENT_LOG_SYSTEM.md](event_log/EVENT_LOG_SYSTEM.md) · [dynamic_workflow/DYNAMIC_WORKFLOW_SYSTEM.md](dynamic_workflow/DYNAMIC_WORKFLOW_SYSTEM.md) · [deep_research/DEEP_RESEARCH_SYSTEM.md](deep_research/DEEP_RESEARCH_SYSTEM.md) · [tool_management/TOOL_MANAGEMENT_SYSTEM.md](tool_management/TOOL_MANAGEMENT_SYSTEM.md) · [security/SECURITY_SYSTEM.md](security/SECURITY_SYSTEM.md) · [goals/GOAL_SYSTEM.md](goals/GOAL_SYSTEM.md)

---

## Three-Layer Navigation

```
┌─────────────────────────────────────────────────────────────┐
│ L1 Runtime Core                                              │
│  base_agent · skill_agent · _factory · _internals · types   │
│  streaming · event_log · config                             │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│ L2 Pipeline (cross-cutting)                                  │
│  middlewares · hooks · context_management · security         │
│  file_snapshot · artifacts · workspace_rules                 │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│ L3 Tool & Orchestration Surface                              │
│  meta_tools · skills · sub_agents · parallel · goals         │
│  dynamic_workflow · deep_research · tool_management          │
│  coordination · workspace_coordination · background_worker     │
└─────────────────────────────────────────────────────────────┘
```

| Layer | Submodules | Role |
|-------|------------|------|
| **Runtime Core** | `base_agent`, `skill_agent`, `_factory`, `_internals`, `streaming`, `types` | Agent 执行循环、流式事件、装配 |
| **Pipeline** | `middlewares`, `hooks`, `context_management`, `security`, `file_snapshot`, `artifacts` | 安全/上下文/快照/工件 |
| **Tool Surface** | `meta_tools`, `skills`, `sub_agents`, `parallel`, `goals`, `tool_management` | LLM 工具与编排 |

**Extension point**: `extensions/` (Harness `AgentExtension` Protocol) · `acp/` (standalone ACP entry)

---

## Easily Confused Modules

| Name A | Name B | Difference |
|--------|--------|------------|
| `api/hooks.py` | `agent/hooks/` | **Server integration facade** (session ContextVar, memory extract, bash registry re-exports) vs **user profile lifecycle hooks** (JSON/YAML, hot-reload) |
| `api/hooks.py` | `core/hooks/` | Integration callables for product code vs **HookEvent / HookResult type definitions** |
| `coordination/` | `workspace_coordination/` | **P2P 邮箱** (TeammateMailbox, JSONL) vs **并行写隔离 + batch merge** |
| `parallel/` | `sub_agents/` | **共享 spawn 路径** (batch/swarm semaphore) vs **子 Agent 生命周期全栈** |
| `agent/artifacts/` | `core/artifacts/` | **运行时生命周期** (registry/vault/UI) vs **类型常量 + 路径 SSOT** |
| `agent/extensions.AgentExtension` | `toolkits/a2a.AgentExtension` | **Harness 插件 Protocol** vs **Google A2A Pydantic 模型**（同名，import 时注意包路径） |
| `agent/streaming/broadcast/` | `observability/` (top-level) | **ToolBroadcastBus side-channel** (chat UI via EventLogger→SSE) vs **Prometheus + Doctor** |
| `infra/pubsub/` | `agent/streaming/broadcast/` | **PubSubBus / Server business SSE** vs **hook tool side-channel bus** |
| `observability/tracing/` | `infra/tracing/` | **ContextVar stdlib 日志关联** vs **OpenTelemetry 分布式追踪** |
| `middlewares/` | `hooks/` | **框架内建** LangChain middleware vs **用户 profile 可配** 生命周期 hook |
| `meta_tools/goals/` | `goals/` | **LLM 工具面** vs **Goal 引擎域逻辑** |

---

## Root File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Agent core module — public API. | — |
| `base_agent.py` | Core | Base Agent — streaming, token tracking, artifacts. | ✅ |
| `skill_agent.py` | Core | SkillAgent — skills, hooks, session lifecycle. | ✅ |
| `_skill_agent_context.py` | Internal | ContextVar + background task utilities. | ✅ |
| `_skill_agent_review.py` | Internal | Session-end review mixin. | ✅ |
| `_skill_agent_tools.py` | Internal | Meta-tools / planner / wiki assembly mixin. | ✅ |
| `skill_agent_factory.py` | Core | Facade — re-exports `create_skill_agent()`. | ✅ |
| `types.py` | Config | AgentRuntimeSpec, EngineParams, run statistics. | ✅ |

| Submodule | Description | L2 Doc |
|-----------|-------------|--------|
| `_factory/` | SkillAgent assembly: builder, mcp_routing | [_factory/_ARCH.md](_factory/_ARCH.md) |
| `_internals/` | Private runtime helpers | [_internals/_ARCH.md](_internals/_ARCH.md) |
| `acp/` | ACP default factory for standalone server | [acp/_ARCH.md](acp/_ARCH.md) |
| `artifacts/` | Artifact lifecycle (registry, vault, UI) | [artifacts/_ARCH.md](artifacts/_ARCH.md) |
| `background_worker/` | Idle task registry, shadow bulkhead | [background_worker/_ARCH.md](background_worker/_ARCH.md) |
| `config/` | Unified config types export | [config/_ARCH.md](config/_ARCH.md) |
| `context_management/` | Context pipeline, compression, cache | [CONTEXT_MANAGEMENT_SYSTEM.md](context_management/CONTEXT_MANAGEMENT_SYSTEM.md) |
| `coordination/` | Subagent P2P mailbox (TeammateMailbox) | [coordination/_ARCH.md](coordination/_ARCH.md) |
| `dynamic_workflow/` | LLM-generated PTC orchestration scripts | [DYNAMIC_WORKFLOW_SYSTEM.md](dynamic_workflow/DYNAMIC_WORKFLOW_SYSTEM.md) |
| `deep_research/` | Multi-phase deep research orchestrator | [DEEP_RESEARCH_SYSTEM.md](deep_research/DEEP_RESEARCH_SYSTEM.md) |
| `errors/` | Execution errors + diagnostics | [ERROR_SYSTEM.md](errors/ERROR_SYSTEM.md) |
| `event_log/` | Full event history (complements checkpointer) | [EVENT_LOG_SYSTEM.md](event_log/EVENT_LOG_SYSTEM.md) |
| `extensions/` | Harness `AgentExtension` Protocol | [extensions/_ARCH.md](extensions/_ARCH.md) |
| `file_snapshot/` | Workspace file versioning / rollback | [file_snapshot/_ARCH.md](file_snapshot/_ARCH.md) |
| `goals/` | Goal-based autonomous loop engine | [GOAL_SYSTEM.md](goals/GOAL_SYSTEM.md) |
| `hooks/` | User-configurable lifecycle hooks | [hooks/_ARCH.md](hooks/_ARCH.md) |
| `meta_tools/` | Agent-bound LangChain meta-tools | [META_TOOLS_SYSTEM.md](meta_tools/META_TOOLS_SYSTEM.md) |
| `middlewares/` | Framework middleware stack | [MIDDLEWARE_SYSTEM.md](middlewares/MIDDLEWARE_SYSTEM.md) |
| `streaming/` | BaseAgent event pipeline + [broadcast/](streaming/broadcast/_ARCH.md) tool SSE | [STREAMING_SYSTEM.md](streaming/STREAMING_SYSTEM.md) |
| `sub_agents/` | Sub-agent lifecycle | [SUB_AGENT_SYSTEM.md](sub_agents/SUB_AGENT_SYSTEM.md) |
| `tool_management/` | Tool registry, layers, dedup | [TOOL_MANAGEMENT_SYSTEM.md](tool_management/TOOL_MANAGEMENT_SYSTEM.md) |
| `workspace_coordination/` | Parallel write isolation + batch merge | [workspace_coordination/_ARCH.md](workspace_coordination/_ARCH.md) |
| `workspace_rules/` | Project context file discovery | [workspace_rules/_ARCH.md](workspace_rules/_ARCH.md) |

## Key Dependencies

- `backends`
- `core` (artifacts constants/paths, hooks types)
- `infra`
- `toolkits`
- `utils`
