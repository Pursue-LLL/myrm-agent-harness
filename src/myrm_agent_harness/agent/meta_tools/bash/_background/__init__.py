"""Background bash process registry package.

Tracks long-running shell jobs spawned via ``bash_code_execute_tool(run_in_background=True)``.
See ``_ARCH.md`` for module index.
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
