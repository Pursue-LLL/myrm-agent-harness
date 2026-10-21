"""Multi-part structured event stream, SQLite projector, and lossless session replayer suite.

[OUTPUT]
- PartKind: Enumeration of granular conversational message parts.
- PartStatus: Lifecycle status of an individual part.
- EventKind: Enumeration of fine-grained streaming event kinds.
- ReasoningPart, TextPart, ToolInvocationPart, ToolResultPart, FilePatchPart, CompactionPart.
- PartEvent: Immutable event envelope for event-bus dispatch and relational projection.
- PartEventStream: Real-time async pub-sub broadcaster with reconnect replay ring buffer.
- SQLitePartProjector: Relational state projector consuming streaming PartEvents.
- SessionReplayer: Zero-loss recovery engine and breakpoint detector from SQLite state.
- SessionSnapshot, ReplayedMessage, ReplayedPart: Reconstructed session state models.

[INPUT]
- __future__

[OUTPUT]
- (模块级副作用与注册)

[POS]
Multi-part structured event stream, SQLite projector, and lossless session replayer suite.
"""

from __future__ import annotations

from myrm_agent_harness.agent.event_stream.event_stream import PartEventStream
from myrm_agent_harness.agent.event_stream.part_types import (
    CompactionPart,
    EventKind,
    FilePatchPart,
    PartEvent,
    PartKind,
    PartStatus,
    ReasoningPart,
    TextPart,
    ToolInvocationPart,
    ToolResultPart,
)
from myrm_agent_harness.agent.event_stream.session_replayer import (
    ReplayedMessage,
    ReplayedPart,
    SessionReplayer,
    SessionSnapshot,
)
from myrm_agent_harness.agent.event_stream.sqlite_projector import (
    SQLitePartProjector,
)

__all__ = [
    "CompactionPart",
    "EventKind",
    "FilePatchPart",
    "PartEvent",
    "PartEventStream",
    "PartKind",
    "PartStatus",
    "ReasoningPart",
    "ReplayedMessage",
    "ReplayedPart",
    "SQLitePartProjector",
    "SessionReplayer",
    "SessionSnapshot",
    "TextPart",
    "ToolInvocationPart",
    "ToolResultPart",
]
