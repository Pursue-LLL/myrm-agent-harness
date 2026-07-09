# runtime/

## Overview

Skill execution runtime: registry, loader, env prep, trust attenuation. **`get_metadata_summary()`** builds XML skill catalogs embedded in meta-tool descriptions (see `meta_tools/skills/select/_ARCH.md`).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Runtime — skill execution runtime. | — |
| attenuator.py | Core | Trust attenuator. Three-layer filtering; model-layer restriction via `middlewares/_skill_tool_choice.py` + `DeferredToolMiddleware`. Execution fallback: `check_trust_attenuation`. | ✅ |
| session_skills_rehydrate.py | Core | Rebuild `loaded_skills` from chat history ∪ `context.session_loaded_skill_names` SSOT at `SkillAgent.run()` start. | ✅ |
| env.py | Core | Skill execution environment preparer before sandbox execution. | ✅ |
| loader.py | Core | Skill document loader and trap injection. | ✅ |
| registry.py | Core | SkillRegistry + get_metadata_summary (XML for tool descriptions, not SystemMessage). | ✅ |

## Key Dependencies

- `backends.skills` (SkillMetadata)
- `skills.mcp` (loader → core_generator for MCP skill metadata)
