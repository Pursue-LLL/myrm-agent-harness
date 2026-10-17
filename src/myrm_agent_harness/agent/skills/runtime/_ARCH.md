# runtime/

## Overview

Skill execution runtime: registry, command path utilities, trust attenuation. **`get_metadata_summary()`** builds XML for HumanMessage `<bound_skills>` blocks (see `skill_catalog_delivery.py` and `meta_tools/skills/select/_ARCH.md`).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Runtime — skill execution runtime. | — |
| attenuator.py | Core | Trust attenuator. Three-layer filtering; `allowed_tools` narrows only by names that are registered or bound (names from other skill ecosystems are ignored and warned once per skill; a skill with no recognized name does not narrow). Model-layer restriction via `middlewares/_skill_tool_choice.py` + `SkillAttenuationMiddleware`. Execution fallback: `check_trust_attenuation`. | ✅ |
| session_skills_rehydrate.py | Core | Rebuild `loaded_skills` from chat history ∪ `context.session_loaded_skill_names` SSOT at `SkillAgent.run()` start. | ✅ |
| command_paths.py | Core | Skill command path utilities: rewrite `.claude/skills/` paths to relative, detect skill script commands in bash execution. | ✅ |
| registry.py | Core | SkillRegistry (`register`, `get_skill`, `get_mcp_skill_for_ipc` backed by `_ipc_mcp_skill_cache` so parent PTC IPC calls survive subagent `clear_mcp_skills()` passes) + `get_metadata_summary` (XML for HumanMessage catalog with explicit intention-anchored and direct-tool precedence routing rules, not tool schema). | ✅ |
| catalog_display.py | Core | resolve_catalog_display_skills + should_mount_skill_search_tool SSOT (inline vs hidden; search mount gate). | ✅ |
| skill_catalog_delivery.py | Core | Frozen baseline plus tail updates: `<bound_skills hash hidden_count>` is written once on the first HumanMessage of a (re)built conversation and never rewritten; on drift `<bound_skills_update hash>` carries the full current list on the new HumanMessage and supersedes earlier lists (`empty` hash announces no skills). What a thread last delivered is read from the thread's own messages (`last_delivered_catalog_key`), so a compaction that drops the blocks makes the next turn deliver the list again. Delivery flow lives in `agent/_internals/skill_catalog_turn.py`. | ✅ |

## Key Dependencies

- `backends.skills` (SkillMetadata)
- `agent.tool_management.tool_layers` (`is_registered_action_tool`: Action Tool name SSOT for `allowed_tools` recognition)
