# discover_capability/

## Overview
Unified Capability Discovery gateway. Indexes deferred native tools (including `skill_analyze_tool`) and bound external skills; AutoMount via `DeferredToolMiddleware`. After all deferred tools register, `sync_discover_capability_tool()` rebuilds the search index (SSOT when `ToolRegistry` is used; `get_meta_tools()` requires `registry` and no longer creates discover inline). Gap detection uses server-supplied `active_tool_groups` (from `derive_active_tool_groups()`, aligned with `BUILTIN_TOOL_ID_TO_GROUP`); `_GAP_TRIGGERS` covers all mapped builtins including `web_search`, `memory`, and `answer_tool`; emits `<CapabilityGap>` / `<SkillGap>` plus SSE only for **disabled** builtins or unbound skills.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| discover_capability_tool.py | Core | Unified discovery meta-tool, index sync, XML output. | ✅ |
| capability_gap.py | Core | Disabled builtin tool / unbound skill gap detection. | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `agent.tool_management`
- `agent.middlewares.deferred_tool_middleware`
