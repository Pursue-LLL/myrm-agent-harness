# engine/

## Overview
Cron scheduling engine internals.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Cron scheduling engine internals. | — |
| executor.py | Core | Single-job execution lifecycle. Delivery gate: incremental skip, `is_silent_output`, output-hash dedup；`monitor_contract_error`（invalid JSON-like）显式记录并按失败链路进入统一告警，重复 contract error 会抑制主通道重复投递；failure 计数持久化异常时回退内存计数保证去重稳定。Runner-level skip via `_record_skipped()`. | ✅ |
| helpers.py | Core | Provides resolve_stagger_ms, is_top_of_hour_cron, compute_stagger_offset_s. | ✅ |
| integrity.py | Core | Merkle chain integrity for cron run records. | ✅ |
| name_generator.py | Core | Intelligently truncates long prompts/commands while preserving readability. | ✅ |
| parser.py | Core | Cron expression parsing and next-run calculation. | ✅ |
| recovery.py | Core | Three-phase startup recovery strategy. | ✅ |
| scheduler.py | Core | Cron scheduling engine. Computes exact sleep durations to the next due job, dispatches | ✅ |

## Key Dependencies

- `infra`
- `observability.tracing` (TracingContext for per-execution trace_id/session_id)
