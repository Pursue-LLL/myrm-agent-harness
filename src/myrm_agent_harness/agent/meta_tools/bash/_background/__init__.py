"""Background bash process registry package.

Public symbols: :class:`BackgroundProcessInfo`, :class:`BackgroundProcessRegistry`,
:class:`BackgroundQuotaError`, :class:`FinishListener`, :class:`ProgressListener`,
:func:`get_background_registry`.
See _ARCH.md for module index.

[POS]
Background bash process registry facade re-exporting registry + types.
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
