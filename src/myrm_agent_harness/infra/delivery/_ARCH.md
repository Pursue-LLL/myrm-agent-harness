# delivery/

## Overview
Message delivery queue. Disk-persistent with automatic retry on failure and pending delivery recovery on startup.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Message delivery queue. Disk-persistent with automatic retry on failure and pending delivery recover | ✅ |
| dead_letter.py | Core | Dead letter queue. Failed messages retry with backoff; invokes `on_permanent_failure` when max retries exceeded; `mark_permanent_failure_notified` dedupes sync-path callbacks. | ✅ |
| deduplication.py | Core | Message deduplicator. Content-hash-based deduplication window to prevent duplicate deliveries. | ✅ |
| file_lock.py | Core | Delivery module file lock wrapper. Prevents duplicate processing during concurrent multi-worker exec | ✅ |
| queue.py | Core | Delivery queue main class. Coordinates storage and recovery, providing enqueue, deliver, and failure | ✅ |
| recovery.py | Core | Delivery recovery logic. Exponential backoff calculation, permanent error identification, and startu | ✅ |
| storage.py | Core | Delivery queue storage layer. Atomic writes prevent data corruption; directory structure isolates pe | ✅ |
| storage_metrics.py | Core | StorageProvider observability layer. Provides operational metrics needed for monitoring and tuning. | ✅ |
| storage_resilience.py | Core | StorageProvider resilience layer. Ensures production availability with typed errors and retry logic. | ✅ |

## Key Dependencies

- `toolkits`
