# background_worker/

## Overview
Background worker module for agent.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Background worker module for agent. | — |
| idle_tasks.py | Core | Default callbacks and tasks for the idle worker. | ✅ |
| idle_worker.py | Core | Idle Task Worker for scheduling background tasks when agent is inactive. | ✅ |
| registry.py | Core | Idle Task Registry for crash-resilient persistence and concurrency control. | ✅ |

## Supported Idle Task Types

| Task Type | Description | Handler Location |
|-----------|-------------|-----------------|
| cognitive_consolidation | Merge and consolidate memory fragments | Built-in (idle_tasks.py) |
| cognitive_subsumption | Erase redundant memories when a Skill is learned | Built-in (idle_tasks.py) |
| session_evidence_extraction | Extract anti-patterns and evidence from session events | Built-in (idle_tasks.py) |
| context_compaction | Compress idle session context and preheat prefix cache | Built-in (idle_tasks.py) |
| auto_skill_extraction | Auto-extract skills from successful agent runs | Via registered handler |

## Key Dependencies

- `runtime`
- `toolkits`
- `agent.context_management`
