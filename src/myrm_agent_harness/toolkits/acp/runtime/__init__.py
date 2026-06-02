"""ACP Runtime backends — unified interface for ACP, SDK, and CLI agents."""

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
