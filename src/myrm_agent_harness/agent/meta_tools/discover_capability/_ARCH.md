# discover_capability/

## Overview
Unified Capability Discovery gateway. Indexes agent-bound searchable skills (MCP PTC + user skills) into a semantic search index. When searchable skills exist, ``sync_discover_capability_tool()`` registers the discovery tool (LLM-facing name: `skill_search_tool`).

**Boundary**: searches the **agent-bound skill library**. External marketplace install uses ``skill_market_tool`` only when that tool is Turn1-mounted (`market_backend` present); otherwise the discovery tool description points users to Settings → Skills → Discover.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| discover_capability_tool.py | Core | Unified discovery meta-tool (LLM name: `skill_search_tool`), index sync, `<BoundSkills>` XML output; description varies by `market_tool_mounted`. | ✅ |
| capability_gap.py | Core | Substring trigger registry (`CAPABILITY_GAP_REGISTRY`, 15 IDs); `detect_capability_gap` for render_ui surface-unavailable intent in server preflight only. Discover miss no longer emits gap blocks/SSE. | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `agent.tool_management`
