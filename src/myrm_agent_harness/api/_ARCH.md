# api/

## Overview
Stable public import surface for external consumers (`myrm-agent-server`, third-party agent frameworks). All symbols are lazy-loaded re-exports; core IP may ship as compiled native extensions in release wheels.

## Not to be confused with

| Path | Role |
|------|------|
| `myrm_agent_harness.api.hooks` | **This package** — integration facade for server/desktop (import here) |
| `myrm_agent_harness.agent.hooks` | User profile lifecycle hook system — see [../agent/hooks/_ARCH.md](../agent/hooks/_ARCH.md) |
| `myrm_agent_harness.core.hooks` | Hook type definitions shared across agent and toolkits |

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Core | Lazy export registry for public API | ✅ |
| factory.py | Core | `create_skill_agent`, `SkillAgent` | ✅ |
| types.py | Core | Runtime and streaming DTOs | ✅ |
| config.py | Core | LLM/Agent configuration types | ✅ |
| protocols.py | Core | Extension-point Protocol definitions | ✅ |
| hooks.py | Core | Session / skill-agent / memory / bash integration hooks（含 task intent 与 memory telemetry 只读契约：budget/injection + injection contract；含 privacy 上下文原语：`build_pseudonym_store` / `set_privacy_policy` / `set_pseudonym_store` / `install_memory_pseudonymizer` / `restore_memory_pseudonymizer` 供后台任务桥接隐私策略、假名化 store 与 regex 假名化闭包） | ✅ |
| skills.py | Core | Skill frontmatter parse and metadata builders | ✅ |
| subagents.py | Core | `build_parent_delegatable_toolkit` — public subagent delegation helper for server wiring；`get_subagent_checkpointer` / `delete_subagent_checkpoint` — shared subagent checkpointer（HITL 审批存活与线程恢复、终态内存清理） | ✅ |
| security.py | Core | `ManagedApprovalPolicy` / `get_process_managed_approval_policy` — process-wide MAP facade for server | ✅ |
| routing.py | Core | `route_task`, `route_task_specialty`, `RoutingTier`, `TaskSpecialty` — public LLM routing facade | ✅ |

## SDK convenience (non-stable)

- `myrm_agent_harness.client.AgentClient` — fluent builder; **not** part of this package. Server should prefer `api.factory.create_skill_agent`.

## Tests

- `tests/api/test_public_surface.py` — public `__all__`, lazy exports, submodule smoke, distribution mode

## Key Dependencies

- `agent._factory.builder` (POS: SkillAgent assembly pipeline)
- `agent.skill_agent.factory` (POS: Agent factory facade re-export)
- `agent.types` (POS: Agent core runtime type definitions)
- `core.events.types` (POS: Event type definitions)
- `backends.skills.protocols` (POS: Skill backend protocol definition)

## Distribution

See [DISTRIBUTION_SYSTEM.md](../../../harness_packaging/DISTRIBUTION_SYSTEM.md).
