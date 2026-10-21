# subagent_watchdog/

## Overview
Subagent execution heartbeat watchdog and zombie cleanup suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Subagent execution heartbeat watchdog and zombie cleanup suite. | — |
| `subagent_heartbeat_tracker.py` | Core | Subagent execution heartbeat tracker and tiered health evaluator. | ✅ |
| `watchdog_types.py` | Core | Strongly typed contracts for subagent execution heartbeat watchdog and zombie cleanup. | ✅ |
| `zombie_cleanup_supervisor.py` | Core | Zombie cleanup supervisor and tiered progressive timeout watchdog for subagents. | ✅ |
