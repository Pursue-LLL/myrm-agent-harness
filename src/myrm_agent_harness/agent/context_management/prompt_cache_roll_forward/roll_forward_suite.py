# [INPUT]: BaseMessage from langchain_core, DynamicRollForwardEngine, CacheMissAnomalyGuard, Headless3DSandboxAdapter, LongTaskTelemetryTracker, types from roll_forward_types
# [OUTPUT]: PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite
# [POS]: myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.roll_forward_suite
"""Unified facade suite for Prompt Cache Dynamic Roll-Forward and Headless 3D Sandbox (Item 330).

Orchestrates cross-tool-round cache roll-forward, cache miss anomaly fuse guards,
pure-CPU headless 3D script execution, and long-horizon task telemetry.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Final
from langchain_core.messages import BaseMessage

from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.cache_miss_anomaly_guard import (
    CacheMissAnomalyGuard,
)
from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.dynamic_roll_forward_engine import (
    DynamicRollForwardEngine,
)
from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.headless_3d_sandbox_adapter import (
    Headless3DSandboxAdapter,
)
from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.long_task_telemetry import (
    LongTaskTelemetryTracker,
)
from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.roll_forward_types import (
    CacheMissAnomalyReport,
    DynamicRollForwardResult,
    Headless3DExecutionResult,
    Headless3DScriptRequest,
    LongTaskIterationSnapshot,
    RollForwardStrategy,
)


class PromptCacheDynamicRollForwardAndHeadless3DSandboxSuite:
    """Industrial suite providing multi-round prompt cache roll-forward and headless 3D execution."""

    def __init__(
        self,
        task_id: str = "default_task",
        roll_forward_strategy: RollForwardStrategy = RollForwardStrategy.STRIP_INTERMEDIATE,
        enable_1h_ttl: bool = True,
        sandbox_workspace: Path | None = None,
        weekly_quota_tokens: int = 50_000_000,
    ) -> None:
        self._lock = threading.RLock()
        self._roll_forward_engine: Final[DynamicRollForwardEngine] = DynamicRollForwardEngine(
            strategy=roll_forward_strategy,
            enable_1h_ttl=enable_1h_ttl,
        )
        self._anomaly_guard: Final[CacheMissAnomalyGuard] = CacheMissAnomalyGuard()
        self._sandbox_3d_adapter: Final[Headless3DSandboxAdapter] = Headless3DSandboxAdapter(
            workspace_root=sandbox_workspace
        )
        self._telemetry_tracker: Final[LongTaskTelemetryTracker] = LongTaskTelemetryTracker(
            task_id=task_id,
            weekly_quota_tokens=weekly_quota_tokens,
        )

    @property
    def roll_forward_engine(self) -> DynamicRollForwardEngine:
        """Dynamic cache breakpoint roll-forward engine."""
        return self._roll_forward_engine

    @property
    def anomaly_guard(self) -> CacheMissAnomalyGuard:
        """Cache miss anomaly and circuit-breaker guard."""
        return self._anomaly_guard

    @property
    def sandbox_3d_adapter(self) -> Headless3DSandboxAdapter:
        """Headless 3D/CAD modeling execution adapter."""
        return self._sandbox_3d_adapter

    @property
    def telemetry_tracker(self) -> LongTaskTelemetryTracker:
        """Long-horizon task telemetry tracker."""
        return self._telemetry_tracker

    @property
    def is_circuit_broken(self) -> bool:
        """Check if execution loop is circuit-broken due to catastrophic cache misses."""
        return self._anomaly_guard.is_circuit_broken

    def advance_cache_breakpoints(
        self,
        messages: list[BaseMessage],
        permanent_indices: list[int] | None = None,
        force_1h_ttl: bool | None = None,
    ) -> tuple[list[BaseMessage], DynamicRollForwardResult]:
        """Roll forward prompt cache breakpoints across tool execution rounds."""
        with self._lock:
            return self._roll_forward_engine.roll_forward(
                messages=messages,
                permanent_indices=permanent_indices,
                force_1h_ttl=force_1h_ttl,
            )

    def record_round_tokens(
        self,
        round_index: int,
        input_tokens: int,
        cache_read_tokens: int,
    ) -> CacheMissAnomalyReport:
        """Audit token usage per round, tripping circuit breaker if severe cold misses persist."""
        with self._lock:
            return self._anomaly_guard.record_round_tokens(
                round_index=round_index,
                input_tokens=input_tokens,
                cache_read_tokens=cache_read_tokens,
            )

    def execute_3d_script(
        self,
        request: Headless3DScriptRequest,
        mock_in_test: bool = False,
    ) -> Headless3DExecutionResult:
        """Run pure-CPU headless 3D CAD modeling script inside sandbox."""
        with self._lock:
            return self._sandbox_3d_adapter.execute_script(
                request=request,
                mock_in_test=mock_in_test,
            )

    def record_task_iteration(
        self,
        iteration_label: str,
        tool_round_index: int,
        input_tokens: int,
        cache_read_tokens: int,
        cost_saved_usd: float,
        preview_artifact_path: str = "",
    ) -> LongTaskIterationSnapshot:
        """Log an iteration version tag (e.g. V1 -> V10 -> V13) and telemetry metrics."""
        with self._lock:
            return self._telemetry_tracker.record_iteration(
                iteration_label=iteration_label,
                tool_round_index=tool_round_index,
                input_tokens=input_tokens,
                cache_read_tokens=cache_read_tokens,
                cost_saved_usd=cost_saved_usd,
                preview_artifact_path=preview_artifact_path,
            )

    def get_telemetry_hud(self) -> dict[str, str | int | float | list[dict[str, str | float | int]]]:
        """Retrieve aggregated HUD metrics for mobile/desktop offline task telemetry."""
        with self._lock:
            return self._telemetry_tracker.get_mobile_telemetry_hud()

    def reset_anomaly_guard(self) -> None:
        """Reset circuit breaker after user intervention."""
        with self._lock:
            self._anomaly_guard.reset_fuse()

    def reset_all(self) -> None:
        """Reset suite telemetry and anomaly state."""
        with self._lock:
            self._anomaly_guard.reset_fuse()
            self._telemetry_tracker.reset()
