# discover_capability/

## Overview
Unified Capability Discovery gateway. Indexes **DISCOVERABLE** native tools (``ToolBindMode.DISCOVERABLE``; excludes ``RUNTIME_ONLY`` hooks like ``_completion_check``) and bound external skills; AutoMount via ``DeferredToolMiddleware``. After all lazy-bound tools register, ``sync_discover_capability_tool()`` rebuilds the search index (SSOT when ``ToolRegistry`` is used).

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
