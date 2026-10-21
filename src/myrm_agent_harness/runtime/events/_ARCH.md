# events/

## Overview
Runtime Events module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| bus.py | Core | Event Bus Implementation | ✅ |
| idle_events.py | Core | `IdleTaskProgressEvent`: structured idle-task progress (`status` is a Literal of working/completed/notification/error/idle; `data` carries structured payload only, user-facing text belongs to the UI layer). | ✅ |
| skill_events.py | Core | Framework DTOs for non-blocking skill-attributed runtime failure events, including session and LoopGuard evidence fields. | ✅ |
| system_events.py | Core | Framework-level typed system event DTOs for subagent lifecycle, delegation policy decisions, and resource metrics. | ✅ |
