# infra/pubsub/

## Overview
Generic in-process pub-sub for Server business notifications (SSE, pairing, btw). **`PubSubBus`** — not chat tool progress (see `agent/streaming/broadcast/ToolBroadcastBus`).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports PubSubBus, PubSubEventProtocol | ✅ |
| event_bus.py | Core | Generic PubSubBus[E] with PubSubEventProtocol contract | ✅ |

## Module Dependencies

- Pure asyncio; no agent or toolkit imports
