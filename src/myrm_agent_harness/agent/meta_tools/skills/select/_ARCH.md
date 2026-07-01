# select/

## Overview

Skill selection meta-tool. Embeds the bound skill catalog (XML via `get_metadata_summary`) in **`skill_select_tool` tool description** — not in SystemMessage. MCP skills (e.g. `mcp_12306_mcp_skill`) appear here; MCP function docs load via tool return / workspace files after selection.

## Architecture

```
Bound skills → get_metadata_summary() → XML in skill_select_tool.description
                                         ↓
                              LLM sees catalog via tool schema
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

**Loaded-skill deduplication**: Uses `get_loaded_skills()` ContextVar to detect already-loaded skills. Returns a concise summary via `_build_reload_summary()` (tool names from `MCPSkillData.tools` + usage hint, ~200 tokens) instead of the full SOP, preventing the select → compact → re-select token waste loop.

**Usage stats**: First load / file read records via `backends.skills.usage_recorder.record_skill_selection()` → `{skill_dir}/.stats.json` for Curator. Reload summaries do not re-record. Turn-level dedupe prevents double-count within one agent run.

**Prompt cache**: stable bound skill list → tool schema hash stable (`tool_definitions_changed` unlikely). Large catalogs increase cached tool-prefix size. `system prompt changed` breaks come from middleware (planner blueprint, SessionNotes, memory), not from this catalog. Explicit injection operates on HumanMessage only — zero impact on prompt prefix cache.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill selection tool module + `get_skill_document` export. | — |
| skill_select_tool.py | Core | Skill selection meta-tool. Builds tool description with skill XML; loads SOP on invoke. Exports `get_skill_document()` for explicit injection. | ✅ |

## Key Dependencies

- `backends.skills` (SkillBackend, SkillMetadata)
- `agent.skills.runtime.registry` (get_metadata_summary)
- `agent.skill_agent` (SkillAgent._preload_explicit_skill — consumer of `get_skill_document`)
