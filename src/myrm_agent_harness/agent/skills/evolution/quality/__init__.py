"""Tool quality monitoring for evolution system.

Monitors tool health and triggers skill evolution when degradation detected.

Framework Layer (开箱即用):
- ToolQualityMonitor: 3维度降级检测（success_rate + p95_latency + server_error_rate）
- ToolFallbackRegistry: 秒级自动切换（<3秒 vs 分钟级FIX evolution）

Control Plane Layer（业务层自定义）:
- GlobalToolMonitor: 跨租户全局监控（参考实现见README.md）
"""

from .fallback import ToolFallbackRegistry
from .monitor import ToolHealthMetrics, ToolQualityMonitor, ToolQualityRecord

__all__ = [
    "ToolFallbackRegistry",
    "ToolHealthMetrics",
    "ToolQualityMonitor",
    "ToolQualityRecord",
]
