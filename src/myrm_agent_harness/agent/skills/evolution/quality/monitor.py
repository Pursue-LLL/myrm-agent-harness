"""Tool quality monitoring with 3-dimensional degradation detection.

[INPUT]
无直接依赖（独立模块）

[OUTPUT]
- ToolHealthMetrics: 3维度工具健康指标（success_rate+p95_latency+server_error_rate）
- ToolQualityRecord: 工具降级记录，兼容OpenSpace接口
- ToolQualityMonitor: 工具质量监控器，滑动窗口统计+LRU eviction

[POS]
Tool quality monitor core. Provides 3-dimension degradation detection (success + latency + error) with sliding window statistics and LRU memory optimization.

"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_SIZE = 100
_DEFAULT_SUCCESS_THRESHOLD = 0.7
_DEFAULT_P95_MULTIPLIER = 2.0
_DEFAULT_SERVER_ERROR_THRESHOLD = 0.3
_MAX_TOOLS = 1000  # LRU eviction limit


@dataclass
class ToolCallRecord:
    """Single tool call record for sliding window."""

    success: bool
    duration_ms: int
    error_type: str | None  # "4xx", "5xx", "timeout", "network", None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ToolHealthMetrics:
    """3-dimensional health metrics for tool quality assessment."""

    tool_name: str
    total_calls: int
    success_count: int
    window_calls: list[ToolCallRecord] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Success rate (0.0-1.0)."""
        if self.total_calls == 0:
            return 1.0
        return self.success_count / self.total_calls

    @property
    def p95_latency(self) -> float:
        """P95 latency in milliseconds."""
        if not self.window_calls:
            return 0.0

        durations = sorted(r.duration_ms for r in self.window_calls)
        p95_index = int(len(durations) * 0.95)
        return durations[p95_index] if p95_index < len(durations) else durations[-1]

    @property
    def server_error_rate(self) -> float:
        """5xx error rate (0.0-1.0)."""
        if not self.window_calls:
            return 0.0

        server_errors = sum(1 for r in self.window_calls if r.error_type == "5xx")
        return server_errors / len(self.window_calls)

    @property
    def baseline_latency(self) -> float:
        """Baseline P50 latency for comparison."""
        if not self.window_calls:
            return 0.0

        durations = sorted(r.duration_ms for r in self.window_calls)
        p50_index = int(len(durations) * 0.5)
        return durations[p50_index] if p50_index < len(durations) else 0.0


@dataclass
class ToolQualityRecord:
    """Tool degradation record passed to evolution system.

    Compatible with OpenSpace ToolQualityRecord interface.
    """

    tool_key: str  # Tool name/identifier
    recent_success_rate: float  # Success rate in sliding window
    total_calls: int  # Total calls tracked
    p95_latency: float  # P95 latency in ms
    server_error_rate: float  # 5xx error rate
    degradation_type: str  # "success", "latency", "server_error", "综合"

    def to_dict(self) -> dict:
        return {
            "tool_key": self.tool_key,
            "recent_success_rate": self.recent_success_rate,
            "total_calls": self.total_calls,
            "p95_latency": self.p95_latency,
            "server_error_rate": self.server_error_rate,
            "degradation_type": self.degradation_type,
        }


class ToolQualityMonitor:
    """Monitor tool health with 3-dimensional degradation detection.

    Features:
    - Sliding window statistics (configurable size)
    - Multi-dimensional health metrics
    - LRU eviction for memory efficiency
    - Async-safe tracking

    Example:
        monitor = ToolQualityMonitor(window_size=100)

        # Track tool calls
        monitor.track_call("github_api", success=True, duration_ms=150)
        monitor.track_call("github_api", success=False, duration_ms=5000, error_type="5xx")

        # Get degraded tools
        degraded = monitor.get_degraded_tools(
            success_threshold=0.7,
            latency_multiplier=2.0,
            server_error_threshold=0.3)
    """

    def __init__(self, *, window_size: int = _DEFAULT_WINDOW_SIZE, max_tools: int = _MAX_TOOLS):
        """Initialize tool quality monitor.

        Args:
            window_size: Sliding window size (default 100)
            max_tools: Max tools to track before LRU eviction (default 1000)
        """
        self._window_size = window_size
        self._max_tools = max_tools

        # tool_name → ToolHealthMetrics
        self._metrics: dict[str, ToolHealthMetrics] = {}

        # LRU tracking: tool_name → last_access_time
        self._access_times: dict[str, float] = {}

    def track_call(self, tool_name: str, success: bool, duration_ms: int, error_type: str | None = None) -> None:
        """Track a single tool call.

        Args:
            tool_name: Tool identifier
            success: Whether call succeeded
            duration_ms: Call duration in milliseconds
            error_type: Error classification ("4xx", "5xx", "timeout", "network", None)
        """
        # LRU eviction if needed
        if len(self._metrics) >= self._max_tools and tool_name not in self._metrics:
            self._evict_lru()

        # Get or create metrics
        if tool_name not in self._metrics:
            self._metrics[tool_name] = ToolHealthMetrics(
                tool_name=tool_name, total_calls=0, success_count=0, window_calls=[]
            )

        metrics = self._metrics[tool_name]

        # Update counters
        metrics.total_calls += 1
        if success:
            metrics.success_count += 1

        # Add to sliding window
        record = ToolCallRecord(success=success, duration_ms=duration_ms, error_type=error_type)
        metrics.window_calls.append(record)

        # Maintain window size
        if len(metrics.window_calls) > self._window_size:
            metrics.window_calls.pop(0)

        # Update LRU
        self._access_times[tool_name] = time.time()

    def get_degraded_tools(
        self,
        *,
        success_threshold: float = _DEFAULT_SUCCESS_THRESHOLD,
        latency_multiplier: float = _DEFAULT_P95_MULTIPLIER,
        server_error_threshold: float = _DEFAULT_SERVER_ERROR_THRESHOLD,
        min_calls: int = 10,
    ) -> list[ToolQualityRecord]:
        """Get tools showing degradation across 3 dimensions.

        Degradation criteria:
        1. Success rate < threshold (default 0.7)
        2. P95 latency > baseline * multiplier (default 2x)
        3. Server error rate (5xx) > threshold (default 0.3)

        Args:
            success_threshold: Min success rate (default 0.7)
            latency_multiplier: P95 vs baseline multiplier (default 2.0)
            server_error_threshold: Max 5xx rate (default 0.3)
            min_calls: Min calls to consider (default 10)

        Returns:
            List of degraded tools with degradation type
        """
        degraded: list[ToolQualityRecord] = []

        for tool_name, metrics in self._metrics.items():
            if metrics.total_calls < min_calls:
                continue

            degradation_reasons: list[str] = []

            # Dimension 1: Success rate
            if metrics.success_rate < success_threshold:
                degradation_reasons.append("success")

            # Dimension 2: Latency degradation
            if metrics.baseline_latency > 0:
                latency_ratio = metrics.p95_latency / metrics.baseline_latency
                if latency_ratio > latency_multiplier:
                    degradation_reasons.append("latency")

            # Dimension 3: Server errors
            if metrics.server_error_rate > server_error_threshold:
                degradation_reasons.append("server_error")

            if degradation_reasons:
                degraded.append(
                    ToolQualityRecord(
                        tool_key=tool_name,
                        recent_success_rate=metrics.success_rate,
                        total_calls=metrics.total_calls,
                        p95_latency=metrics.p95_latency,
                        server_error_rate=metrics.server_error_rate,
                        degradation_type="+".join(degradation_reasons),
                    )
                )

        return degraded

    def get_recovered_tools(
        self,
        previous_degraded: list[str],
        *,
        success_threshold: float = _DEFAULT_SUCCESS_THRESHOLD,
        min_calls: int = 10,
    ) -> list[str]:
        """Detect tools that have recovered from degradation.

        Args:
            previous_degraded: List of tool names that were previously degraded
            success_threshold: Min success rate for recovery (default 0.7)
            min_calls: Min calls to confirm recovery (default 10)

        Returns:
            List of tool names that have recovered
        """
        recovered: list[str] = []

        for tool_name in previous_degraded:
            metrics = self._metrics.get(tool_name)
            if not metrics or metrics.total_calls < min_calls:
                continue

            # Recovered if success rate back above threshold
            if metrics.success_rate >= success_threshold:
                recovered.append(tool_name)

        return recovered

    def get_stats(self) -> dict:
        """Get monitoring statistics.

        Returns:
            Dict with:
            - total_tools: Total tools tracked
            - tools_with_calls: Tools with at least 1 call
            - avg_success_rate: Average success rate across all tools
        """
        if not self._metrics:
            return {
                "total_tools": 0,
                "tools_with_calls": 0,
                "avg_success_rate": 0.0,
            }

        tools_with_calls = [m for m in self._metrics.values() if m.total_calls > 0]
        avg_success = sum(m.success_rate for m in tools_with_calls) / len(tools_with_calls) if tools_with_calls else 0.0

        return {
            "total_tools": len(self._metrics),
            "tools_with_calls": len(tools_with_calls),
            "avg_success_rate": avg_success,
        }

    def _evict_lru(self) -> None:
        """Evict least recently used tool (LRU eviction)."""
        if not self._access_times:
            return

        # Find LRU tool
        lru_tool = min(self._access_times, key=self._access_times.get)  # type: ignore
        del self._metrics[lru_tool]
        del self._access_times[lru_tool]

        logger.debug(f"[ToolQualityMonitor] LRU evicted: {lru_tool}")
