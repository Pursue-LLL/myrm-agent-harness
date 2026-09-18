"""Local Working Memory Block package.

[INPUT]
- context_management.working_memory.block::LocalWorkingMemoryBlock (POS: 执行引擎运行时工作台核心，基于 ContextVar 实现并发强隔离的手边工作区)
- context_management.working_memory.marks::WorkingMemoryMark (POS: Core memory abstraction layer for message metadata tags)
- context_management.working_memory.types::LocalWorkingState (POS: 工作台领域类型定义层，提供运行时任务推进与避坑防线所需的强类型数据模型)

[OUTPUT]
- LocalWorkingMemoryBlock: 手边工作台核心控制器
- LocalWorkingState / SubtaskItem / SubtaskStatus / TrapRecord: 工作台领域类型与子任务流转状态
- WorkingMemoryMark / IMMUNE_MARKS 及 mark 读写与驱逐免疫原语

[POS]
手边工作台的包级统一出口。向 harness 运行时与上下文管理层暴露 Working Memory 的规范公开 API。
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

