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
| hooks.py | Core | Session / skill-agent / memory / bash integration hooks (incl. task intent) | ✅ |
| skills.py | Core | Skill frontmatter parse and metadata builders | ✅ |

## SDK convenience (non-stable)

- `myrm_agent_harness.client.AgentClient` — fluent builder; **not** part of this package. Server should prefer `api.factory.create_skill_agent`.

## Tests

- `tests/api/test_public_surface.py` — public `__all__`, lazy exports, submodule smoke, distribution mode

## Key Dependencies

- `agent._factory.builder` (POS: SkillAgent assembly pipeline)
- `agent.skill_agent_factory` (POS: Agent factory facade re-export)
- `agent.types` (POS: Agent core runtime type definitions)
- `core.events.types` (POS: Event type definitions)
- `backends.skills.protocols` (POS: Skill backend protocol definition)

## Distribution

See [DISTRIBUTION_SYSTEM.md](../../../harness_packaging/DISTRIBUTION_SYSTEM.md).
