"""Local Working Memory Block package.

Provides lightweight, in-memory execution state tracking and turn-tail workbench injection.
"""

from myrm_agent_harness.agent.context_management.working_memory.block import (
    LocalWorkingMemoryBlock,
)
from myrm_agent_harness.agent.context_management.working_memory.types import (
    LocalWorkingState,
    SubtaskItem,
    SubtaskStatus,
    TrapRecord,
)

__all__ = [
    "LocalWorkingMemoryBlock",
    "LocalWorkingState",
    "SubtaskItem",
    "SubtaskStatus",
    "TrapRecord",
]
