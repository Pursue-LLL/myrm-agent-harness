# execution_checklist/

## Overview

Lightweight session execution checklist (Path B SSOT). Complements `planner_tool` (Path A) — never active together.

## Files

| File | Role |
|------|------|
| `__init__.py` | Public re-exports for state helpers and tool factory |
| `state.py` | Pydantic models + `.myrm/execution_checklist.json` + `resolve_checklist_workspace_root()` |
| `events.py` | `tasks_steps` SSE emission (`is_plan=false`) |
| `tool.py` | `update_execution_checklist_tool` factory (workspace via `resolve_checklist_workspace_root`) |

## Bind conditions

- `enable_task_tracking=True` and no `/planner/plan.json` and not Goal session
- Resume when checklist file exists (same mutual exclusion with plan)
