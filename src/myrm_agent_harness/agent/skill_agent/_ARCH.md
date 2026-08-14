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
| `_privacy_context.py` | Internal | Session-end privacy context helper — `reestablish_privacy_context` / `teardown_privacy_context` rebuild security config + PseudonymStore + PII closure from the agent's persisted SecurityConfig after run-end cleanup cleared the ContextVars, and restore the previous values afterwards. | ✅ |
| `review.py` | Internal | Session-end review mixin (SkillAgentReviewMixin). `_cleanup_session` wraps end_session flush and fire-and-forget auto-extraction in the re-established privacy context (see `_privacy_context.py`), then triggers wiki archive and skill review. | ✅ |
| `tools.py` | Internal | Meta-tools / todo_write / wiki assembly mixin (SkillAgentToolsMixin). | ✅ |

## Key Dependencies

- `agent.base_agent` (BaseAgent)
- `agent.skills` (SkillMetadata)
- `agent.types` (AgentRuntimeConfig)
- `agent._factory` (builder)
