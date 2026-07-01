# agent/streaming/broadcast/

## Overview
Real-time **tool call broadcasting** to chat UI (SSE/WebSocket). **`ToolBroadcastBus`** singleton + **`ToolCallBroadcaster`** hook listener.

**Not** [`observability/`](../../../observability/_ARCH.md) (metrics/Doctor) or [`infra/pubsub/`](../../../infra/pubsub/_ARCH.md) (Server business SSE).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports ToolBroadcastBus, ToolCallBroadcaster, ToolCallEventData | ✅ |
| event_bus.py | Core | ToolBroadcastBus — async pub-sub with backpressure for tool events | ✅ |
| tool_call_broadcaster.py | Core | Hook listener publishing PRE/POST tool events | ✅ |
| catchup.py | Core | CatchupBriefExtractor for inbox summaries | ✅ |
| types.py | Config | ToolCallEventData, EventCallback | ✅ |

## Key Dependencies

- `agent.hooks`, `agent.event_log`, `agent.streaming.types`
