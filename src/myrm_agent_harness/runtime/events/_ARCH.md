# events/

## Overview
Runtime Events module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| bus.py | Core | Event Bus Implementation | ✅ |
| idle_events.py | Core | Events related to idle background tasks. | ✅ |
| skill_events.py | Core | Framework DTOs for non-blocking skill-attributed runtime failure events, including session and LoopGuard evidence fields. | ✅ |
| system_events.py | Core | Framework-level typed system event DTOs for subagent lifecycle, delegation policy decisions, and resource metrics. | ✅ |
