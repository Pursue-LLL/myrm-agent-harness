"""Background bash process registry package.

[POS]
Tracks long-running shell jobs spawned via ``bash_code_execute_tool(run_in_background=True)``.
See ``_ARCH.md`` for module index.

[INPUT]
- 后台 bash 进程生命周期事件（spawn / poll / reap）

[OUTPUT]
- BackgroundProcessRegistry: 后台进程注册表
- get_background_registry(): 全局注册表访问器
"""

from myrm_agent_harness.agent.meta_tools.bash._background.registry import (
    BackgroundProcessRegistry,
    get_background_registry,
)
from myrm_agent_harness.agent.meta_tools.bash._background.types import (
    BackgroundProcessInfo,
    BackgroundQuotaError,
    FinishListener,
    ProgressListener,
)

__all__ = [
    "BackgroundProcessInfo",
    "BackgroundProcessRegistry",
    "BackgroundQuotaError",
    "FinishListener",
    "ProgressListener",
    "get_background_registry",
]
