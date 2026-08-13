"""ACP Runtime backends — unified interface for ACP, SDK, and CLI agents.

[INPUT]
- toolkits.acp.runtime._base::BaseRuntime (POS: Base class for RuntimeBackend implementations.) [lazy]
- toolkits.acp.runtime.pool::RuntimePool (POS: Runtime pool management layer. Provides multi-backend unified management, concurrency control, health monitoring, and config-driven registration — the central dispatcher of the runtime system) [lazy]

[OUTPUT]
- BaseRuntime: lazy-imported runtime backend base class
- RuntimePool: lazy-imported unified runtime instance pool

[POS]
ACP runtime direction — external agents are delegated to over a unified RuntimeBackend interface.
"""

from __future__ import annotations

__all__ = [
    "BaseRuntime",
    "RuntimePool",
]


def __getattr__(name: str) -> object:
    if name == "BaseRuntime":
        from ._base import BaseRuntime

        globals()[name] = BaseRuntime
        return BaseRuntime

    if name == "RuntimePool":
        from .pool import RuntimePool

        globals()[name] = RuntimePool
        return RuntimePool

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
