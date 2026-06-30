# meta_tools/

## Overview
Agent meta-tools module. Provides tools that depend on Agent framework infrastructure (Bash, File Ops, File Search, Skill system).

Detailed design: [META_TOOLS_SYSTEM.md](META_TOOLS_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent meta-tools module. Provides tools that depend on Agent framework infrastructure (Bash, File Op | ✅ |
| answer_user_tool.py | Core | Agent answer-phase gating tool. Scheduling signal for completion_guard middleware. | ✅ |
| diagnostics_tool.py | Core | Framework-level read-only diagnostics tool. It exposes existing Harness health | ✅ |

| Submodule | Description |
|-----------|-------------|
| bash/ | Bash tool module (includes PTC — Python scripts invoke all Agent tools via `import myrm_tools`). |
| discover_capability/ | Unified Capability Discovery gateway. |
| file_ops/ | File operations tool module (Claude Code compatible). |
| file_search/ | File search tool module (Claude Code compatible). |
| goals/ | Goal interaction tools — LLM tools for querying/completing goals. |
| clarification/ | Structured HITL clarification (`ask_question_tool`) — schemas + LangChain adapter. |
| interaction/ | UI rendering (`render_ui_tool`) — depends on agent artifact context. |
| http/ | HTTP request toolkit. Supports streaming upload, progress callbacks, streaming download, and concurr |
| llm_map/ | Batch LLM-map agent tool adapter. See [llm_map/_ARCH.md](llm_map/_ARCH.md). |
| skills/ | Skills submodule. |
| spawn_subagent/ | Spawn subagent meta-tool module. |

## Key Dependencies

- `agent.goals` (goals/ sub-module)
- `backends`
- `observability`
- `toolkits`
- `utils`
