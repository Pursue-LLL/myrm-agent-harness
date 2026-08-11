# skill_agent/

## Overview
SkillAgent domain package — the concrete SkillAgent class, its mixins, ContextVar
session state, and the factory facade. Internal implementation lives in sibling
modules; the package root is the single import surface for this domain.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | SkillAgent domain public API — re-exports SkillAgent, mixins, ContextVar getters/setters, factory. | — |
| `skill_agent.py` | Core | SkillAgent — extends BaseAgent with skill system, hooks, and session lifecycle. | ✅ |
| `context.py` | Internal | Module-level ContextVar management (memory manager, loaded skills, task intent, runtime budget), background task utilities, SkillAgentContextMixin (`_prepare_context`). | ✅ |
| `factory.py` | Core | SkillAgent assembly facade — re-exports `create_skill_agent()`. | ✅ |
| `preload.py` | Core | `[use skill]` explicit SOP preload mixin for SkillAgent. | ✅ |
| `review.py` | Internal | Session-end review mixin (SkillAgentReviewMixin). | ✅ |
| `tools.py` | Internal | Meta-tools / todo_write / wiki assembly mixin (SkillAgentToolsMixin). | ✅ |

## Key Dependencies

- `agent.base_agent` (BaseAgent)
- `agent.skills` (SkillMetadata)
- `agent.types` (AgentRuntimeConfig)
- `agent._factory` (builder)
