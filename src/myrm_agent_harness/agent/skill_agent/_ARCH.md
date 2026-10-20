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
| `context.py` | Internal | Module-level ContextVar management (memory manager, task intent, runtime budget with configured/injected rule counts, injection status), the run-scoped loaded-skills list (one mutable list per run that tools append to in place, so a skill loaded inside a tool is visible to later tool calls and model calls; `get_loaded_skills()` returns a snapshot; `reset_loaded_skills()` opens a new scope for a run or a nested run), background task utilities, SkillAgentContextMixin (`_prepare_context`). | ✅ |
| `factory.py` | Core | SkillAgent assembly facade — re-exports `create_skill_agent()`. | ✅ |
| `preload.py` | Core | `[use skill]` explicit SOP preload mixin for SkillAgent. Turns the references of a `[use a,b]` prefix into skills through `skill_reference` (fresh turn; for a message with attachments, i.e. content blocks, only the first block — the user's own words — may carry the tag, so attachment text can never invoke a skill) and re-derives them from the persisted wire message when an approval resumes a parked turn (`_resolve_resumed_turn_skills`), so a resumed run governs itself with the same skills as the run it continues. | ✅ |
| `skill_reference.py` | Core | The `[use a,b]` grammar and reference resolution. `parse_use_tag` → `UseTag(references, tag, text)` recognizes the tag only at the very start of the text (tag-first contract: a host that decorates the query with a banner or context must put it behind the tag). `resolve_skill_reference` maps one reference onto a skill: exact name, then storage skill id, then a canonical spelling (case, `-`/`_`/space, `_skill` suffix) that must be unique. The WebUI sends catalog names (`hookprobe-1a2b`) while backends list runtime names (`hookprobe_1a2b_skill`); both reach the same skill. | ✅ |
| `hook_lifecycle.py` | Core | Hook lifecycle mixin for SkillAgent. Framework hooks (tool-call broadcaster, evolution) register once per session registry. Skill hooks follow explicit user consent only: every skill named by `[use a,b,c]` (or `run(active_skill=...)`, or the same prefix of a resumed turn) has its `hooks:` resolved from the stored SKILL.md (metadata first), activated as a run-scoped group (`SkillHookActivation`) and released in `run()`'s `finally`. Skills the model loads on its own never register hooks. | ✅ |
| `_privacy_context.py` | Internal | Session-end privacy context helper — `reestablish_privacy_context` / `teardown_privacy_context` rebuild security config + PseudonymStore + PII closure from the agent's persisted SecurityConfig after run-end cleanup cleared the ContextVars, and restore the previous values afterwards. | ✅ |
| `turn_loaded_skills.py` | Internal | Turn-end receipt bridge: `build_turn_loaded_skills_payload` turns this run's loaded ∪ bound skills into UI-safe rows (name, id, content hash, load state) for message-end metadata. | — |
| `review.py` | Internal | Session-end review mixin (SkillAgentReviewMixin). `_cleanup_session` wraps end_session flush and fire-and-forget auto-extraction in the re-established privacy context (see `_privacy_context.py`), then triggers wiki archive and skill review. The review runs only when an `on_skill_review_ready` consumer is wired (`_should_trigger_skill_review` returns False without one), so a host that omits the callback pays no review LLM call. | ✅ |
| `tools.py` | Internal | Meta-tools / todo_write / wiki assembly mixin (SkillAgentToolsMixin). | ✅ |

## Key Dependencies

- `agent.base_agent` (BaseAgent)
- `agent.skills` (SkillMetadata)
- `agent.types` (AgentRuntimeConfig)
- `agent._factory` (builder)
