# meta_tools/

## Overview
Agent meta-tools module. Provides tools that depend on Agent framework infrastructure (Bash, File Ops, File Search, Skill system).

Detailed design: [META_TOOLS_SYSTEM.md](META_TOOLS_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent meta-tools module. Provides tools that depend on Agent framework infrastructure (Bash, File Op | ✅ |
| answer_user_tool.py | Core | Agent answer-phase gating tool. Scheduling signal for completion_guard middleware. | ✅ |

| Submodule | Description |
|-----------|-------------|
| bash/ | Bash tool module (includes PTC — Python scripts invoke all Agent tools via `import myrm_tools`). |
| discover_capability/ | Unified Capability Discovery gateway. |
| file_ops/ | File operations tool module (Claude Code compatible). |
| file_search/ | File search tool module (Claude Code compatible). |
| goals/ | Goal interaction tools — LLM tools for querying/completing goals. |
| progress/ | Main-agent todo progress (`todo_write`, workspace todos SSOT). |
| clarification/ | Structured HITL clarification (`ask_question_tool`) — schemas + LangChain adapter. |
| interaction/ | UI rendering (`render_ui_tool`, `update_ui_data_tool`) — UIArtifact context; v3.1 progressive spec + fail-closed type/graph/action/registry validation. |
| skills/ | Skills submodule (`skill_discovery_tool` DISCOVERABLE when ToolRegistry is used). |
| spawn_subagent/ | LLM 子 Agent 委派（`delegate_task_tool` 等；≠ PTC `dynamic_workflow/tools.py`） |

## Key Dependencies

- `agent.goals` (goals/ sub-module)
- `backends`
- `observability`
- `toolkits`
- `utils`
