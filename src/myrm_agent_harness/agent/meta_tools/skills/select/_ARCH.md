# select/

## Overview

Skill selection meta-tool. Bound skill catalog (`get_metadata_summary` XML) is injected into the **first HumanMessage** via `skill_catalog_delivery.py` — not in `skill_select_tool` tool description. MCP skills (e.g. `mcp_12306_mcp_skill`) appear in that catalog; MCP function docs load via tool return / workspace files after selection.

## Architecture

```
Bound skills → resolve_catalog_display_skills() → get_metadata_summary()
                                         ↓
                    ensure_skill_catalog_in_messages() → first HumanMessage <bound_skills>
                                         ↓
                              LLM sees catalog via messages[]
                                         ↓
                    skill_select_tool.description = static rules only (prompt-cache stable)
                                         ↓
                    ┌── explicit [use X] → SkillAgent._preload_explicit_skill()
                    │                      → 0-roundtrip SOP injection into HumanMessage
                    │                      → fallback to Rule 6 on any error
                    │
                    └── implicit (LLM auto-select) → skill_select_tool(skill_names)
                                         ↓
                         ┌── first load → full SOP ToolMessage (~5000 tokens)
                         └── already loaded → concise summary (~200 tokens)
```

**Explicit skill injection**: When the user explicitly invokes a skill (via slash command or command palette), the message arrives as `[use skill_name] args`. `SkillAgent._preload_explicit_skill()` detects this pattern, calls `get_skill_document()` to load the SOP, and injects it directly into the query with an `[IMPORTANT: ...]` header. This eliminates one LLM round trip (2-5s + 500-2000 token savings per invocation). On any failure (skill not found, SOP error), the query passes through unchanged for Rule 6 fallback.

**Loaded-skill deduplication**: Uses `get_loaded_skills()` ContextVar to detect already-loaded skills. Returns a concise summary via `build_reload_summary()` / `build_reload_summary_with_index()` in `skill_document_loader.py` (tool names from `MCPSkillData.tools` + compact linked index + `file_path` hint, ~200 tokens) instead of the full SOP, preventing the select → compact → re-select token waste loop.

**L1 disclosure footer** (`l1_disclosure_footer.py`): On first load, `get_skill_document()` in `skill_document_loader.py` appends `[Linked files]` (from `list_skill_resources`, allowed subdirs only, capped) and `[Skill config]` (schema defaults ∪ instance `config_overrides`, redacted) to the ToolMessage/HumanMessage body only — not SystemMessage. MCP skills skip footer. Instance map wired from server `default_skill_instances` → harness `_default_skill_instances` (same SSOT as env bash injection).

**Cross-turn persistence**: `SkillAgent.run()` calls `rehydrate_loaded_skills_from_history()` (`agent/skills/runtime/session_skills_rehydrate.py`) before the first model call. It merges prior `skill_select_tool` evidence from `chat_history` with `context.session_loaded_skill_names` (server SSOT on `Chat.session_loaded_skill_names`, survives compaction and the 50-message history window). Bundle `[use s1,s2]` preload registers **every** successfully injected skill in `loaded_skills` before the first model call so trust attenuation unions all `allowed_tools`.

**Usage stats**: First load / file read records via `backends.skills.usage_recorder.record_skill_selection()` → `{skill_dir}/.stats.json` for Curator. Reload summaries do not re-record. Turn-level dedupe prevents double-count within one agent run.

**Prompt cache**: `skill_select_tool` description bytes are fully static (no skill names or manage-tool rules); `hidden_count` is explained in the static description and on the HumanMessage ``<bound_skills>`` attribute. Bind changes update messages[] prefix, not tool schema — avoids `tool_definitions_changed`. New-message and HITL `Command(resume=…)` paths refresh the first HumanMessage catalog via `agent_runtime.apply_bound_skill_catalog_for_stream` / `apply_bound_skill_catalog_for_resume` and rebuild the in-process `skill_search_tool` index when the bind list changes (same snapshot as catalog; tool schema bytes unchanged). Explicit injection operates on HumanMessage only — zero impact on tool-prefix cache.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill selection tool module + `get_skill_document` export. | — |
| skill_select_tool.py | Core | Static-description skill selection meta-tool; invoke handler loads SOP. | ✅ |
| skill_document_loader.py | Core | SOP load pipeline, L2 file read, reload summaries, L1 footer orchestration. | ✅ |
| l1_disclosure_footer.py | Core | L1 linked-files index + config block footer for `get_skill_document`. | ✅ |

## Key Dependencies

- `backends.skills` (SkillBackend, SkillMetadata)
- `agent.skills.runtime.registry` (get_metadata_summary)
- `agent.skill_agent` (SkillAgent._preload_explicit_skill — consumer of `get_skill_document`)
