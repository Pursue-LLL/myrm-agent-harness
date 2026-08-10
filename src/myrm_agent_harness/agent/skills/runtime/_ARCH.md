# runtime/

## Overview

Skill execution runtime: registry, loader, command path utilities, trust attenuation. **`get_metadata_summary()`** builds XML for HumanMessage `<bound_skills>` blocks (see `skill_catalog_delivery.py` and `meta_tools/skills/select/_ARCH.md`).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Runtime — skill execution runtime. | — |
| attenuator.py | Core | Trust attenuator. Three-layer filtering; model-layer restriction via `middlewares/_skill_tool_choice.py` + `SkillAttenuationMiddleware`. Execution fallback: `check_trust_attenuation`. | ✅ |
| session_skills_rehydrate.py | Core | Rebuild `loaded_skills` from chat history ∪ `context.session_loaded_skill_names` SSOT at `SkillAgent.run()` start. | ✅ |
| command_paths.py | Core | Skill command path utilities: rewrite `.claude/skills/` paths to relative, detect skill script commands in bash execution. | ✅ |
| loader.py | Core | Skill document loader and trap injection. | ✅ |
| registry.py | Core | SkillRegistry + get_metadata_summary (XML for HumanMessage catalog, not tool schema). | ✅ |
| catalog_display.py | Core | resolve_catalog_display_skills + should_mount_skill_search_tool SSOT (inline vs hidden; search mount gate). | ✅ |
| skill_catalog_delivery.py | Core | strip/reinject `<bound_skills hidden_count="N">` on first HumanMessage (stream prep + resume checkpoint refresh via `agent_runtime.apply_bound_skill_catalog_for_*`; catalog changes on either path conditionally rebuild `skill_search_tool` index when hidden_count > 0). | ✅ |

## Key Dependencies

- `backends.skills` (SkillMetadata)
- `skills.mcp` (loader → core_generator for MCP skill metadata)
