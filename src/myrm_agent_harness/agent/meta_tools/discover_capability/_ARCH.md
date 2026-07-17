# discover_capability/

## Overview
Unified Capability Discovery gateway. Indexes external skills (MCP PTC + user skills) into a semantic search index. When searchable skills exist, ``sync_discover_capability_tool()`` registers the discovery tool.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| discover_capability_tool.py | Core | Unified discovery meta-tool, index sync, XML output. | ✅ |
| capability_gap.py | Core | Disabled builtin tool / unbound skill gap detection; CAPABILITY_GAP_REGISTRY triggers; consumed by discover miss + stream preflight. | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- `agent.tool_management`
