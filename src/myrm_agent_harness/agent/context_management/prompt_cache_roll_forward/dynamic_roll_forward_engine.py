# [INPUT]: BaseMessage, RollForwardStrategy, DynamicRollForwardResult, MAX_CACHE_BREAKPOINTS from roll_forward_types
# [OUTPUT]: DynamicRollForwardEngine
# [POS]: myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.dynamic_roll_forward_engine
"""Cross-tool-round dynamic prompt cache roll-forward engine (Item 330).

Advances prompt cache breakpoints dynamically across tool execution rounds,
stripping intermediate stale breakpoints and ensuring the newest tool results
are cached with 90% cost discount while adhering to the <= 4 breakpoint ceiling.
"""

from __future__ import annotations

import copy
from typing import Final
from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.roll_forward_types import (
    MAX_CACHE_BREAKPOINTS,
    DynamicRollForwardResult,
    RollForwardStrategy,
)


class DynamicRollForwardEngine:
    """Engine that rolls forward cache_control breakpoints across tool rounds."""

    def __init__(
        self,
        strategy: RollForwardStrategy = RollForwardStrategy.STRIP_INTERMEDIATE,
        max_breakpoints: int = MAX_CACHE_BREAKPOINTS,
        enable_1h_ttl: bool = True,
    ) -> None:
        self._strategy: Final[RollForwardStrategy] = strategy
        self._max_breakpoints: Final[int] = min(max_breakpoints, MAX_CACHE_BREAKPOINTS)
        self._enable_1h_ttl: Final[bool] = enable_1h_ttl

    @property
    def strategy(self) -> RollForwardStrategy:
        """Active roll-forward strategy."""
        return self._strategy

    @property
    def max_breakpoints(self) -> int:
        """Active breakpoint capacity ceiling."""
        return self._max_breakpoints

    def roll_forward(
        self,
        messages: list[BaseMessage],
        permanent_indices: list[int] | None = None,
        force_1h_ttl: bool | None = None,
    ) -> tuple[list[BaseMessage], DynamicRollForwardResult]:
        """Advance prompt cache breakpoint to the newest tool message or sequence tail.

        Args:
            messages: List of conversation messages (BaseMessage instances).
            permanent_indices: Optional list of message indices that must retain their cache_control.
            force_1h_ttl: Override whether to inject explicit 1h TTL.

        Returns:
            tuple of (modified_messages, DynamicRollForwardResult)
        """
        if not messages:
            return (
                [],
                DynamicRollForwardResult(
                    total_messages=0,
                    stripped_breakpoints_count=0,
                    preserved_permanent_indices=[],
                    new_active_breakpoint_indices=[],
                    rolled_forward_index=-1,
                    max_allowed_breakpoints=self._max_breakpoints,
                ),
            )

        cloned_messages = [copy.deepcopy(m) for m in messages]
        total_len = len(cloned_messages)

        # 1. Determine permanent breakpoint indices (default: first SystemMessage if present)
        active_permanent: set[int] = set()
        if permanent_indices:
            active_permanent.update(idx for idx in permanent_indices if 0 <= idx < total_len)
        else:
            # Default convention: preserve the first SystemMessage as permanent anchor
            for idx, msg in enumerate(cloned_messages):
                if isinstance(msg, SystemMessage) or getattr(msg, "type", "") == "system":
                    active_permanent.add(idx)
                    break

        # 2. Identify the target message to roll forward onto:
        # Prefer the newest ToolMessage if tool execution just completed, otherwise the absolute tail
        target_roll_forward_idx = -1
        for idx in range(total_len - 1, -1, -1):
            msg = cloned_messages[idx]
            if isinstance(msg, ToolMessage) or getattr(msg, "type", "") == "tool":
                target_roll_forward_idx = idx
                break

        if target_roll_forward_idx < 0:
            target_roll_forward_idx = total_len - 1

        # 3. Strip obsolete intermediate cache_control markers
        stripped_count = 0
        for idx, msg in enumerate(cloned_messages):
            if idx in active_permanent:
                continue
            if idx == target_roll_forward_idx:
                continue

            # Strip from additional_kwargs
            if "cache_control" in msg.additional_kwargs:
                msg.additional_kwargs.pop("cache_control", None)
                stripped_count += 1

            # Strip from multi-content block dicts if present
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict) and "cache_control" in block:
                        block.pop("cache_control", None)
                        stripped_count += 1

        # 4. Inject cache_control on permanent anchors
        use_1h = self._enable_1h_ttl if force_1h_ttl is None else force_1h_ttl
        cache_marker: dict[str, str] = {"type": "ephemeral", "ttl": "1h"} if use_1h else {"type": "ephemeral"}

        final_active_indices: list[int] = []
        for p_idx in sorted(active_permanent):
            cloned_messages[p_idx].additional_kwargs["cache_control"] = cache_marker.copy()
            final_active_indices.append(p_idx)

        # 5. Inject rolled-forward cache_control on newest target message
        if target_roll_forward_idx not in final_active_indices:
            cloned_messages[target_roll_forward_idx].additional_kwargs["cache_control"] = cache_marker.copy()
            final_active_indices.append(target_roll_forward_idx)

        # 6. Enforce ceiling <= max_breakpoints
        final_active_indices.sort()
        if len(final_active_indices) > self._max_breakpoints:
            # Keep target_roll_forward_idx and earliest permanent, prune intermediate
            surplus = len(final_active_indices) - self._max_breakpoints
            pruned_indices = final_active_indices[1 : 1 + surplus]
            for idx in pruned_indices:
                cloned_messages[idx].additional_kwargs.pop("cache_control", None)
                final_active_indices.remove(idx)
                stripped_count += 1

        result = DynamicRollForwardResult(
            total_messages=total_len,
            stripped_breakpoints_count=stripped_count,
            preserved_permanent_indices=sorted(active_permanent),
            new_active_breakpoint_indices=final_active_indices,
            rolled_forward_index=target_roll_forward_idx,
            max_allowed_breakpoints=self._max_breakpoints,
        )

        return cloned_messages, result
