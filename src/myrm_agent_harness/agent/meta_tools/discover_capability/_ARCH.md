# discover_capability/

## Overview
Unified Capability Discovery gateway. Indexes agent-bound searchable skills (MCP PTC + user skills) into a semantic search index. When searchable skills exist, ``sync_discover_capability_tool()`` registers the discovery tool.

**Boundary**: searches the **agent-bound skill library**. To install new skills from external markets, use ``skill_discovery_tool`` instead.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| discover_capability_tool.py | Core | Unified discovery meta-tool, index sync, `<BoundSkills>` XML output. | ✅ |
| capability_gap.py | Core | Disabled builtin tool / unbound skill gap detection; `CAPABILITY_GAP_REGISTRY` (16 GUI-togglable IDs incl. `web_crawl`); consumed by discover miss + stream preflight. | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `agent.tool_management`
