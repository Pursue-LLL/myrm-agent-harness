# agent/streaming/broadcast/

## Overview
In-process **tool-call side-channel** pub-sub. **`ToolBroadcastBus`** singleton + **`ToolCallBroadcaster`** hook listener.

**Chat UI tool progress** uses `ToolCallBroadcaster` → `EventLogger` → agent SSE stream (see `agent/streaming/stream_dispatcher.py`), not bus subscribers.

**Bus subscribers** are for server-side consumers (e.g. A/B test in `app/lifecycle/skills.py`).

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
