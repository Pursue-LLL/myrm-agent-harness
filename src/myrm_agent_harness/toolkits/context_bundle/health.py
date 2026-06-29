"""Scene health probe adapters for ContextBundle index registry.

[INPUT]
- pathlib::Path (POS: Python path library)
- collections.abc::Callable, Awaitable (POS: async probe callback)
- .spec::ContextScene (POS: context bundle specification types)
- .index::ContextIndexBackend (POS: index backend protocol)

[OUTPUT]
- MemorySceneHealthBackend: memory path writability probe
- WorkspaceSceneHealthBackend: delegates to server-provided workspace probe

[POS]
Lightweight health adapters without reading user content. Workspace readiness probe
is injected from Server because toolkit layer must not import business services.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from .spec import ContextScene

HealthProbe = Callable[[], Awaitable[str]]


class MemorySceneHealthBackend:
    """Probe memory scene directory writability."""

    scene = ContextScene.MEMORY

    def __init__(self, memory_path: Path) -> None:
        self._memory_path = memory_path

    async def health(self) -> str:
        target = self._memory_path if self._memory_path.exists() else self._memory_path.parent
        if target.exists() and os.access(target, os.W_OK):
            return "ready"
        return "critical"


class WorkspaceSceneHealthBackend:
    """Probe workspace scene readiness via injected Server callback."""

    scene = ContextScene.WORKSPACE

    def __init__(self, probe: HealthProbe) -> None:
        self._probe = probe

    async def health(self) -> str:
        return await self._probe()


class StaticSceneHealthBackend:
    """Return a fixed readiness status for scenes without index backends yet."""

    def __init__(self, scene: ContextScene, status: str) -> None:
        self.scene = scene
        self._status = status

    async def health(self) -> str:
        return self._status
