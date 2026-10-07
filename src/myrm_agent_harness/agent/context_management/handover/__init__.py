"""Package facade for handover.

[INPUT]
- agent.context_management.handover.cross_device_attachment_hub::ActiveSessionAttachmentHub,
  TerminalOutputRingBuffer (POS: Central bus orchestrating cross-device session handover and terminal
  attachment.)
- agent.context_management.handover.handover_types::AttachmentCatchupSnapshot, AttachmentMode, DeviceInfo,
  DeviceKind, HandoverSessionHandle, SessionExecutionState, TerminalOutputChunk (POS: Types and models for
  handover.)

[OUTPUT]
- Re-exports: ActiveSessionAttachmentHub, AttachmentCatchupSnapshot, AttachmentMode, DeviceInfo, DeviceKind,
  HandoverSessionHandle, SessionExecutionState, TerminalOutputChunk, TerminalOutputRingBuffer

[POS]
Package facade for handover.
"""

# ============================================================================
# Cross-Device Session Handover & Attachment Package (Item 159)
# ============================================================================

from .cross_device_attachment_hub import (
    ActiveSessionAttachmentHub,
    TerminalOutputRingBuffer,
)
from .handover_types import (
    AttachmentCatchupSnapshot,
    AttachmentMode,
    DeviceInfo,
    DeviceKind,
    HandoverSessionHandle,
    SessionExecutionState,
    TerminalOutputChunk,
)

__all__ = [
    "ActiveSessionAttachmentHub",
    "AttachmentCatchupSnapshot",
    "AttachmentMode",
    "DeviceInfo",
    "DeviceKind",
    "HandoverSessionHandle",
    "SessionExecutionState",
    "TerminalOutputChunk",
    "TerminalOutputRingBuffer",
]
