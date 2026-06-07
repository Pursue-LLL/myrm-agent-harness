# api/

## Overview
Stable public import surface for external consumers (`myrm-agent-server`, third-party agent frameworks). All symbols are lazy-loaded re-exports; core IP may ship as compiled native extensions in release wheels.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Core | Lazy export registry for public API | ✅ |
| factory.py | Core | `create_skill_agent`, `SkillAgent` | ✅ |
| types.py | Core | Runtime and streaming DTOs | ✅ |
| config.py | Core | LLM/Agent configuration types | ✅ |
| protocols.py | Core | Extension-point Protocol definitions | ✅ |

## Tests

- `tests/api/test_public_surface.py` — public `__all__`, lazy exports, submodule smoke, distribution mode

## Key Dependencies

- `agent.skill_agent_factory` (POS: Agent factory function)
- `agent.types` (POS: Agent core runtime type definitions)
- `core.events.types` (POS: Event type definitions)
- `backends.skills.protocols` (POS: Skill backend protocol definition)

## Distribution

See [DISTRIBUTION_SYSTEM.md](../../../harness_packaging/DISTRIBUTION_SYSTEM.md).
