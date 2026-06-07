# infra/

## Overview
Agent Skills Evolution Infra module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| background_task_manager.py | Core | Background evolution task management with observability and graceful shutdown. | ✅ |
| confirmation.py | Core | Batch LLM confirmation for evolution candidates. | ✅ |
| integration.py | Core | Integration helpers for skill evolution system: Error-Aware Smart Quarantine (1-Strike/3-Strikes), 15-Call Sliding Window trace slice trigger. | ✅ |
| metrics.py | Core | Aggregates evolution metrics across all skills for system-level insights. | ✅ |
| monitor.py | Core | Periodic skill health monitoring and proactive evolution trigger. | ✅ |
| queue.py | Core | Defers non-critical evolutions to background queue to avoid blocking main flow. | ✅ |
| tracker.py | Core | Skill quality tracking and FIX evolution triggering. | ✅ |

## Key Dependencies

- `runtime`
- `toolkits`
