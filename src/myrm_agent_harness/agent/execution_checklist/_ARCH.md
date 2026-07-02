# execution_checklist/

## Overview

Lightweight session execution checklist (Path B SSOT). Complements `planner_tool` (Path A) — never active together.

## Files

| File | Role |
|------|------|
| `__init__.py` | Public re-exports for state helpers and tool factory |
| `state.py` | Pydantic models + `.myrm/execution_checklist.json` + workspace resolve/cleanup + metadata key |
| `events.py` | `tasks_steps` SSE payloads (`is_plan=false`); resume via `dispatch_custom_event` |
| `tool.py` | Persist checklist; return JSON metadata `{workspace_root}` for SSE in `event_handlers` |

## Bind conditions

- `enable_task_tracking=True` and no `/planner/plan.json` and not Goal session
- Resume when checklist file exists (same mutual exclusion with plan)
