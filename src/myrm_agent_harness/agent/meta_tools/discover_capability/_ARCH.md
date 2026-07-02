# discover_capability/

## Overview
Unified Capability Discovery gateway. Indexes deferred native tools (including `skill_analyze_tool`) and bound external skills; AutoMount via `DeferredToolMiddleware`. After all deferred tools register, `sync_discover_capability_tool()` rebuilds the search index. When search misses, `capability_gap.py` emits `<CapabilityGap>` / `<SkillGap>` plus SSE for one-click entitlement fixes.

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
