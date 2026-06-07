"""Context index registration protocol.

[INPUT]
- typing::Protocol (POS: Python structural typing protocol)
- .spec::ContextScene (POS: context bundle specification types)

[OUTPUT]
- ContextIndexBackend: pluggable index backend contract (roadmap #2 mount point)
- ContextIndexRegistry: scene-scoped backend registry

[POS]
Registration-only index protocol for unified context_search. Backends attach per scene without
coupling memory or workspace search implementations inside the context bundle facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .spec import ContextScene


class ContextIndexBackend(Protocol):
    """Minimal index backend contract for future unified context_search."""

    scene: ContextScene

    async def health(self) -> str:
        """Return ready | degraded | missing without reading user content."""
        ...


@dataclass
class ContextIndexRegistry:
    """Scene-scoped index backend registry."""

    _backends: dict[ContextScene, ContextIndexBackend] = field(default_factory=dict)

    def register(self, backend: ContextIndexBackend) -> None:
        self._backends[backend.scene] = backend

    def get(self, scene: ContextScene) -> ContextIndexBackend | None:
        return self._backends.get(scene)

    async def health_by_scene(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for scene in ContextScene:
            backend = self._backends.get(scene)
            if backend is None:
                result[scene.value] = "missing"
                continue
            result[scene.value] = await backend.health()
        return result
