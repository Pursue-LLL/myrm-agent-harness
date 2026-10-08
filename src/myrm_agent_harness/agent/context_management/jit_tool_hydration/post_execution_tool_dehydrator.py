# [INPUT]: JITToolHydrationConfig
# [OUTPUT]: PostExecutionToolDehydrator
# [POS]: agent/context_management/jit_tool_hydration/post_execution_tool_dehydrator.py

"""Post-execution tool dehydrator and schema garbage collector.

[INPUT]
- JITToolHydrationConfig: Configuration parameters for core whitelist and thresholds.

[OUTPUT]
- PostExecutionToolDehydrator: Manages session turn lifecycle to dehydrate used tools back to catalog.

[POS]
Schema lifecycle garbage collection and post-turn dehydration layer.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .hydration_types import JITToolHydrationConfig


class PostExecutionToolDehydrator:
    """Tracks active tool mounts per session and reclaims schema space after execution cycles."""

    def __init__(self, config: JITToolHydrationConfig | None = None) -> None:
        self._config = config or JITToolHydrationConfig()
        # session_id -> set of actively mounted tool names
        self._session_active_tools: dict[str, set[str]] = {}
        # session_id -> cumulative tokens saved across turns
        self._cumulative_tokens_saved: dict[str, int] = {}

    def get_active_hydrated_tools(self, session_id: str) -> tuple[str, ...]:
        """Returns tuple of currently mounted tool names for the given session."""
        return tuple(self._session_active_tools.get(session_id, set()))

    def mark_tools_hydrated(
        self,
        session_id: str,
        tool_names: Sequence[str],
    ) -> None:
        """Records tools that were hydrated during the current turn."""
        if session_id not in self._session_active_tools:
            self._session_active_tools[session_id] = set()
        self._session_active_tools[session_id].update(tool_names)

    def record_turn_savings(self, session_id: str, tokens_saved: int) -> None:
        """Accumulates saved token count for telemetry and reporting."""
        current = self._cumulative_tokens_saved.get(session_id, 0)
        self._cumulative_tokens_saved[session_id] = current + max(0, tokens_saved)

    def dehydrate_after_turn(
        self,
        session_id: str,
        preserve_core: bool = True,
    ) -> tuple[str, ...]:
        """Evicts non-core hydrated tools back to the virtual catalog, returning pruned tool names."""
        if session_id not in self._session_active_tools:
            return ()

        active_set = self._session_active_tools[session_id]
        core_set = set(self._config.core_tools_whitelist) if preserve_core else set()

        pruned_tools: list[str] = []
        remaining_tools: set[str] = set()

        for tool_name in active_set:
            if tool_name in core_set:
                remaining_tools.add(tool_name)
            else:
                pruned_tools.append(tool_name)

        self._session_active_tools[session_id] = remaining_tools
        return tuple(pruned_tools)

    def get_cumulative_savings(self, session_id: str) -> int:
        """Returns total estimated tokens saved for this session across all turns."""
        return self._cumulative_tokens_saved.get(session_id, 0)

    def clear_session(self, session_id: str) -> None:
        """Purges tracking state upon session termination."""
        if session_id in self._session_active_tools:
            del self._session_active_tools[session_id]
        if session_id in self._cumulative_tokens_saved:
            del self._cumulative_tokens_saved[session_id]
