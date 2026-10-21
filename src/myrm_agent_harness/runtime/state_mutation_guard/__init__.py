"""会话状态并发变异写隔离、无锁冲突防护与事件管道生命周期安全包装套件.

对外导出核心类型与引擎实现.

[INPUT]
- (none — 标准库与内建依赖)

[OUTPUT]
- (模块级副作用与注册)

[POS]
会话状态并发变异写隔离、无锁冲突防护与事件管道生命周期安全包装套件.
"""

from myrm_agent_harness.runtime.state_mutation_guard.mutation_guard_types import (
    ChannelLifecycleState,
    ChannelPutResult,
    ChannelPutStatus,
    PatchCommitResult,
    PatchConflictError,
    PatchConflictStrategy,
    SessionStateSnapshot,
    StateMutationPatch,
)
from myrm_agent_harness.runtime.state_mutation_guard.safe_event_channel import (
    SafeEventChannel,
)
from myrm_agent_harness.runtime.state_mutation_guard.session_state_mutator import (
    IsolatedBranchView,
    SessionStateMutator,
)
from myrm_agent_harness.runtime.state_mutation_guard.task_lifecycle_sentinel import (
    TaskLifecycleScope,
)

__all__ = [
    "ChannelLifecycleState",
    "ChannelPutResult",
    "ChannelPutStatus",
    "IsolatedBranchView",
    "PatchCommitResult",
    "PatchConflictError",
    "PatchConflictStrategy",
    "SafeEventChannel",
    "SessionStateMutator",
    "SessionStateSnapshot",
    "StateMutationPatch",
    "TaskLifecycleScope",
]
