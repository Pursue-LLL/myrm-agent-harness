# infra/events/

## Overview
Generic in-process asyncio EventBus for framework-level pub/sub (per-subscriber queues, topic backlog, idempotency dedup, backpressure). Distinct from `runtime/events/` (agent lifecycle) and `toolkits/acp/event_bus.py` (ACP runtime).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports EventBus, EventProtocol | ✅ |
| event_bus.py | Core | Generic EventBus[E] with EventProtocol contract | ✅ |

## Module Dependencies

- Pure asyncio; no agent or toolkit imports
