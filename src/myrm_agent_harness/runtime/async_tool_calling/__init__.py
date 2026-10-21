"""Async Non-Blocking Tool Calling and Overlapped Inference Suite.

Provides lightweight tool future handles, overlapped inference synchronization,
mandatory sync-wait opt-out enforcement, and out-of-band notification draining.

[INPUT]
- async_tool_dispatcher
- async_tool_types
- overlapped_inference_coordinator

[OUTPUT]
- (模块级副作用与注册)

[POS]
Async Non-Blocking Tool Calling and Overlapped Inference Suite.
"""

from .async_tool_dispatcher import AsyncToolDispatcher
from .async_tool_types import (
    AsyncToolMetadata,
    ToolCompletedEvent,
    ToolExecutionMode,
    ToolFutureHandle,
    ToolJobResult,
    ToolJobStatus,
)
from .overlapped_inference_coordinator import OverlappedInferenceCoordinator

__all__ = [
    "AsyncToolDispatcher",
    "AsyncToolMetadata",
    "OverlappedInferenceCoordinator",
    "ToolCompletedEvent",
    "ToolExecutionMode",
    "ToolFutureHandle",
    "ToolJobResult",
    "ToolJobStatus",
]
