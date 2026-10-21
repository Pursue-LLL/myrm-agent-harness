"""Strongly typed contracts for double-layer stream exception preservation and resilient replay.

Benchmarked against IHUI-AI commit 6ce28c444 streamChat error chain preservation invariants:
- Double-layer exception preservation: prevents inner catch-blocks from swallowing raw JSON or socket errors.
- Distinguishes retriable network glitches from non-recoverable protocol or authentication errors.
- Checkpoints streaming chunks with sequential IDs to enable mid-stream resumption.

[OUTPUT]
- StreamErrorKind: Canonical category of streaming communication failure.
- StreamChunkEvent: Individual sequentially ordered chunk in a streaming session.
- NestedStreamException: Preserves outer pipeline error alongside raw inner cause.
- StreamReplayState: Resumption cursor and retry budget state.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- StreamErrorKind
- StreamChunkEvent
- NestedStreamError
- NestedStreamException
- StreamReplayState

[POS]
Strongly typed contracts for double-layer stream exception preservation and resilient replay.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class StreamErrorKind(StrEnum):
    """Categorization of stream transmission and parsing failures."""

    TRANSPORT_RESET = "transport_reset"
    """Socket reset by peer, broken pipe, or abrupt network disconnection."""

    TIMEOUT = "timeout"
    """Read/connect timeout waiting for stream chunk."""

    MALFORMED_CHUNK = "malformed_chunk"
    """Incomplete, corrupted, or non-parseable JSON chunk delivered mid-stream."""

    PROTOCOL_VIOLATION = "protocol_violation"
    """Unexpected HTTP status, missing SSE headers, or misaligned framing."""

    UPSTREAM_API_ERROR = "upstream_api_error"
    """Model provider rate-limiting, quota exhaustion, or server error."""


@dataclass(frozen=True)
class StreamChunkEvent:
    """Ordered token or event chunk received from the streaming server."""

    seq_id: int
    event_type: str
    content: str
    is_final: bool = False
    timestamp: float = field(default_factory=time.time)


class NestedStreamError(Exception):
    """Preserves outer architectural failure context while retaining raw inner cause.

    Eliminates the silent-failure / endless-spinning spinner anti-pattern by ensuring
    the caller receives both high-level classification and the exact root error.
    """

    def __init__(
        self,
        error_kind: StreamErrorKind,
        outer_message: str,
        cause_error_name: str,
        cause_details: str,
        is_retriable: bool,
        raw_chunk_preview: str = "",
        last_acked_seq: int = -1,
    ) -> None:
        super().__init__(f"[{error_kind.value}] {outer_message} (Cause: {cause_error_name}: {cause_details})")
        self.error_kind = error_kind
        self.outer_message = outer_message
        self.cause_error_name = cause_error_name
        self.cause_details = cause_details
        self.is_retriable = is_retriable
        self.raw_chunk_preview = raw_chunk_preview
        self.last_acked_seq = last_acked_seq


# Backward compatibility alias
NestedStreamException = NestedStreamError


@dataclass(frozen=True)
class StreamReplayState:
    """Reconnection cursor and retry state for an active streaming session."""

    session_id: str
    last_acked_seq: int = -1
    retry_attempts: int = 0
    max_retries: int = 3
    accumulated_content: str = ""
    is_active: bool = True
