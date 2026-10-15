# delivery/

## Overview
Durable delivery persistence. Disk-persistent pending/failed storage, dead-letter retry with backoff and a permanent-failure notification ledger; the delivery queue is owned by the host.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Durable delivery persistence and dead-letter retry. | ✅ |
| dead_letter.py | Core | Dead letter queue. Failed messages retry with backoff; invokes `on_permanent_failure` when max retries exceeded; optional `notification_ledger` for persistent notify dedupe; `mark_permanent_failure_notified` dedupes sync-path callbacks. | ✅ |
| `notification_ledger.py` | Core | `PermanentFailureNotificationLedger` protocol + in-memory test double | ✅ |
| storage.py | Core | Delivery queue storage layer. Atomic writes; pending/attempting phase lifecycle; directory structure isolates pending and failed deliveries. | ✅ |
| storage_metrics.py | Core | StorageProvider observability layer. Provides operational metrics needed for monitoring and tuning. | ✅ |
| storage_resilience.py | Core | StorageProvider resilience layer. Ensures production availability with typed errors and retry logic. | ✅ |

## Key Dependencies

- `toolkits`
