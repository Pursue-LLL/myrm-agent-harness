# tests/agent/streaming/broadcast/

## Overview

Unit tests for `myrm_agent_harness.agent.streaming.broadcast` (`ToolBroadcastBus`, `ToolCallBroadcaster`, catchup).

## File Index

| File | Role |
|------|------|
| `test_event_types.py` | ToolCallEventData / callback types |
| `test_tool_call_broadcaster.py` | Hook PRE/POST publish + EventLog |
| `test_tool_heartbeat.py` | Heartbeat / backpressure |
| `test_progress_sink.py` | Progress sink integration |
| `test_catchup_brief_extractor.py` | CatchupBriefExtractor |
| `test_p0_fixes.py` | Truncation / backpressure regressions |

## Key Dependencies

- `myrm_agent_harness.agent.streaming.broadcast`
