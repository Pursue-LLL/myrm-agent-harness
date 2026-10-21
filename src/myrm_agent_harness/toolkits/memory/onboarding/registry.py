"""Registry for discovering, managing, and querying external agent source adapters.

[INPUT]
- typing: Dict, List, Optional
- .adapters: BaseAgentSourceAdapter, CursorSourceAdapter, ClaudeCodeSourceAdapter, CodexSourceAdapter, HermesSourceAdapter, OpenClawSourceAdapter

[OUTPUT]
- OnboardingSourceRegistry: Central registry for registering and querying agent adapters.

[POS]
Harness framework registry coordinating multi-source agent adapters for zero-friction
onboarding discovery and historical conversation extraction.
"""

from __future__ import annotations

from .adapters import (
    BaseAgentSourceAdapter,
    ClaudeCodeSourceAdapter,
    CodexSourceAdapter,
    CursorSourceAdapter,
    HermesSourceAdapter,
    OpenClawSourceAdapter,
)


class OnboardingSourceRegistry:
    """Manages active agent source adapters and coordinates discovery on the host system."""

    def __init__(self, register_defaults: bool = True) -> None:
        self._adapters: dict[str, BaseAgentSourceAdapter] = {}
        if register_defaults:
            self.register(CursorSourceAdapter())
            self.register(ClaudeCodeSourceAdapter())
            self.register(CodexSourceAdapter())
            self.register(HermesSourceAdapter())
            self.register(OpenClawSourceAdapter())

    def register(self, adapter: BaseAgentSourceAdapter) -> None:
        """Register a new or custom agent source adapter."""
        self._adapters[adapter.source_id] = adapter

    def get(self, source_id: str) -> BaseAgentSourceAdapter | None:
        """Retrieve an adapter by source ID."""
        return self._adapters.get(source_id)

    def list_adapters(self) -> list[BaseAgentSourceAdapter]:
        """Return all registered source adapters."""
        return list(self._adapters.values())

    def detect_active_sources(self) -> list[str]:
        """Detect and return source IDs of all active agents on the host system."""
        active: list[str] = []
        for source_id, adapter in self._adapters.items():
            if adapter.detect_active():
                active.append(source_id)
        return active

    def clear(self) -> None:
        """Clear all registered adapters (useful for isolated unit testing)."""
        self._adapters.clear()
