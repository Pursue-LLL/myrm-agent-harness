# execution_checklist/

## Overview

Lightweight session execution checklist (Path B SSOT). Complements `planner_tool` (Path A) — never active together.

## Files

| File | Role |
|------|------|
| `state.py` | Pydantic models + `.myrm/execution_checklist.json` under **chat workspace_root** |
| `events.py` | `tasks_steps` SSE emission (`is_plan=false`) |
| `tool.py` | `update_execution_checklist_tool` factory (workspace via session ContextVar) |

## Bind conditions

- `enable_task_tracking=True` and no `/planner/plan.json` and not Goal session
- Resume when checklist file exists (same mutual exclusion with plan)
