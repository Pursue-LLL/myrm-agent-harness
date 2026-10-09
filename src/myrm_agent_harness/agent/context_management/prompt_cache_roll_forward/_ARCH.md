# prompt_cache_roll_forward/

## Overview

Prompt Cache Dynamic Roll-Forward and Headless 3D Sandbox Suite (Item 330).
Provides dynamic prompt cache breakpoint roll-forward across tool execution rounds,
continuous cache miss spike anomaly circuit-breaking, pure-CPU headless 3D CAD modeling,
and long-horizon task version telemetry.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public symbols for Prompt Cache Dynamic Roll-Forward and Headless 3D Sandbox Suite. | ✅ |
| `cache_miss_anomaly_guard.py` | Guard | Consecutive cache miss spike detector and circuit-breaker fuse. | ✅ |
| `dynamic_roll_forward_engine.py` | Core | Dynamic prompt cache breakpoint roll-forward engine across tool rounds. | ✅ |
| `headless_3d_sandbox_adapter.py` | Adapter | Pure-CPU sandbox headless 3D CAD script execution and preview adapter. | ✅ |
| `long_task_telemetry.py` | Telemetry | Long-horizon task iteration versioning (V1->V13) and quota HUD tracker. | ✅ |
| `roll_forward_suite.py` | Facade | Unified facade suite orchestrating roll-forward, anomaly fuse, and 3D sandbox. | ✅ |
| `roll_forward_types.py` | Types | Strongly-typed domain models, states, and telemetry contracts. | ✅ |
