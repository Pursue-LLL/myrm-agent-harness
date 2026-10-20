# timeline_visualizer/

## Overview
Execution timeline visualizer and step lifecycle inspection engine for tasks and skill invocations.
Provides millisecond-precision step durations, hierarchical tree construction, waterfall chronological ordering, IO metrics, and graceful interruption/barge-in tracking.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Facade | Re-exports core timeline data models and execution collector. | — |
| `timeline_models.py` | Models | Data contracts for step nodes, statuses, types, and IO metrics. | ✅ |
| `timeline_collector.py` | Core | Thread-safe collector managing step lifecycles and compiling tree/waterfall views. | ✅ |
| `_ARCH.md` | Architecture | Architectural documentation and component taxonomy. | — |

## Key Dependencies
- Standard library (`time`, `threading`, `uuid`, `dataclasses`, `typing`)
- Decoupled from concrete LLM providers or database backends.
