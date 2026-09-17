"""Local Working Memory Block package.

Provides lightweight, in-memory execution state tracking and turn-tail workbench injection.
"""

from myrm_agent_harness.agent.context_management.working_memory.block import (
    LocalWorkingMemoryBlock,
)
from myrm_agent_harness.agent.context_management.working_memory.marks import (
    IMMUNE_MARKS,
    WorkingMemoryMark,
    get_message_marks,
    has_message_marks,
    is_eviction_immune,
    with_message_marks,
)
from myrm_agent_harness.agent.context_management.working_memory.types import (
    LocalWorkingState,
    SubtaskItem,
    SubtaskStatus,
    TrapRecord,
)

__all__ = [
    "IMMUNE_MARKS",
    "LocalWorkingMemoryBlock",
    "LocalWorkingState",
    "SubtaskItem",
    "SubtaskStatus",
    "TrapRecord",
    "WorkingMemoryMark",
    "get_message_marks",
    "has_message_marks",
    "is_eviction_immune",
    "with_message_marks",
]

