# runtime/

## Overview
Agent run() lifecycle control parameters. All based on ContextVar for request-level isolation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent run() lifecycle control parameters. All based on ContextVar for request-level isolation. | — |
| cancellation.py | Core | Cancellation token + CancellationRegistry（cancel / cancel_all for E-Stop）+ `run_until_cancelled`（token 取消时中止仍阻塞在驱动调用上的操作，轮询 0.25s，取消后最多 3s 收尾；调用方自身被取消时一并取消内部任务） | ✅ |
| cancellation_metrics.py | Core | Cancellation metrics data structures. | ✅ |
| progress_sink.py | Core | Progress event push mechanism. Tools implicitly obtain a sink via ContextVar to push intermediate pr | ✅ |
| steering.py | Core | Steering token mechanism. Allows external message injection (steer/redirect) during Agent runtime. Steer waits for tool boundary; redirect immediately breaks astream and preserves partial output. | ✅ |
| wakeup_registry.py | Core | Global registry for async wakeup events (Idle Wakeup). | ✅ |
| background_job_finish_registry.py | Core | ``BackgroundJobFinishResult`` DTO + ``BackgroundJobFinishHandler`` Protocol; server registers handler at warmup for natural bash background job ``exited`` events (no headless LLM). | ✅ |

## Key Dependencies

- `agent`
