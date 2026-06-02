# runtime/

## Overview
Agent run() lifecycle control parameters. All based on ContextVar for request-level isolation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent run() lifecycle control parameters. All based on ContextVar for request-level isolation. | — |
| cancellation.py | Core | Cancellation token mechanism. Provides request-level cancellation state management with graceful asy | ✅ |
| cancellation_metrics.py | Core | Cancellation metrics data structures. | ✅ |
| progress_sink.py | Core | Progress event push mechanism. Tools implicitly obtain a sink via ContextVar to push intermediate pr | ✅ |
| steering.py | Core | Steering token mechanism. Allows external message injection during Agent runtime to interrupt the cu | ✅ |
| wakeup_registry.py | Core | Global registry for async wakeup events (Idle Wakeup). | ✅ |

## Key Dependencies

- `agent`
