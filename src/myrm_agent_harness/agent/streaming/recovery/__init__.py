"""Streaming recovery strategies — composed mixins for StreamRecoveryMixin.

[INPUT]
- recovery.stream_recovery::StreamRecoveryMixin (POS: 恢复策略组合主 Mixin)
- recovery.stream_recovery_continuation::StreamContinuationRecoveryMixin (POS: steering/subagent/goal continuation recovery)
- recovery.stream_recovery_oneshot::OneshotRecoveryMixin (POS: one-shot recovery strategies)
- recovery.stream_recovery_truncation::StreamTruncationRecoveryMixin (POS: length truncation recovery)

[OUTPUT]
- StreamRecoveryMixin, StreamContinuationRecoveryMixin, OneshotRecoveryMixin, StreamTruncationRecoveryMixin

[POS]
Package entry for streaming recovery strategies. stream_executor consumes StreamRecoveryMixin
via multiple inheritance and recovery helpers directly from the sub-modules.
"""

from .disconnection_recovery import ResilientDisconnectionRecoveryManager
from .recovery_types import (
    ConnectionState,
    ReplayBatch,
    ReplayStatus,
    StagedAction,
    StructuredStreamEvent,
    dict_to_event,
    event_to_dict,
)
from .replay_buffer import CircularEventReplayBuffer
from .stream_recovery import StreamRecoveryMixin
from .stream_recovery_continuation import StreamContinuationRecoveryMixin
from .stream_recovery_oneshot import OneshotRecoveryMixin
from .stream_recovery_truncation import StreamTruncationRecoveryMixin

__all__ = [
    "CircularEventReplayBuffer",
    "ConnectionState",
    "OneshotRecoveryMixin",
    "ReplayBatch",
    "ReplayStatus",
    "ResilientDisconnectionRecoveryManager",
    "StagedAction",
    "StreamContinuationRecoveryMixin",
    "StreamRecoveryMixin",
    "StreamTruncationRecoveryMixin",
    "StructuredStreamEvent",
    "dict_to_event",
    "event_to_dict",
]
