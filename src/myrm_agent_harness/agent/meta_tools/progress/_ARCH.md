# meta_tools/progress/

## Overview

Main-agent **todo progress meta-tool** — workspace-backed todos for opt-in multi-step tasks (`planning` builtin group).

**Placement rule**: Session-bound todo progress lives under `agent/meta_tools/progress/` (same category as `meta_tools/bash/`). Do not add a sibling directory under `agent/` for LangChain tools, and do not put this in `toolkits/` (toolkits must not import `agent/`).

SSOT: `{workspace_root}/.myrm/progress/todos.json`

## File Index

| File | Role | Description |
|------|------|-------------|
| __init__.py | Package | Public exports for progress meta-tool |
| schemas.py | Config | `TodoItem`, `TodoStore`, plan-compat adapter for Goal API |
| storage.py | Core | Read/write/merge todos in chat workspace (atomic write via `infra.atomic_write`) |
| events.py | Core | Emit `tasks_steps` for ProgressSteps UI |
| todo_write_tool.py | Core | LangChain `todo_write` factory (main agent, no sub-agent LLM) |

## Bind conditions

- `enable_planning=True`, or resume when `.myrm/progress/todos.json` exists in workspace

## Server hydrate (myrm-agent-server)

- `app/platform_utils/workspace_session.to_workspace_session_id` — map chat id → `chat_{id}` workspace key
- `GET /api/v1/goals/{chat_id}/plan` — reads SSOT and returns plan-compat shape for GoalControlPlane

## Key Dependencies

- `agent.middlewares._session_context` (workspace root)
- LangGraph `dispatch_custom_event` for SSE progress

## Do not place here

- Generic agent-agnostic engines → `toolkits/` (must not import `agent/`)
- Large autonomous engines with separate LLM tool surface → `agent/<domain>/` + thin `meta_tools/<domain>/` (see `goals/` pattern)
