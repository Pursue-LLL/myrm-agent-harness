"""
[INPUT]: Raw stream events, chunk tokens, model/provider tags, and final stream termination signals.
[OUTPUT]: Immutable StreamCallOutcome enum, StreamCallSession records, and StreamMetricsAggregate statistics.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/stream_metrics/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StreamCallOutcome(str, Enum):
    """流式调用最终结果枚举（排除中间 chunk 计数污染）"""

    SUCCESS = "SUCCESS"  # 正常完整流式生成完毕
    ERROR = "ERROR"  # 中途发生异常错误
    CANCELLED = "CANCELLED"  # 用户或客户端主动中止取消
    TIMEOUT = "TIMEOUT"  # 首字响应或流接收超时


@dataclass
class StreamCallSession:
    """单次流式调用的全生命周期跟踪状态"""

    call_id: str
    model_name: str
    provider: str
    start_time_ms: float
    ttft_ms: Optional[float] = None
    end_time_ms: Optional[float] = None
    total_duration_ms: Optional[float] = None
    chunk_count: int = 0
    total_tokens: int = 0
    outcome: Optional[StreamCallOutcome] = None
    error_message: Optional[str] = None
    is_finalized: bool = False


@dataclass
class StreamMetricsAggregate:
    """流式调用聚合度量指标（基于最终调用结果归因，杜绝 chunk 污染）"""

    total_calls: int
    success_calls: int
    error_calls: int
    cancelled_calls: int
    timeout_calls: int
    total_chunks: int
    total_tokens: int
    avg_ttft_ms: float
    avg_duration_ms: float
    success_rate_pct: float
    chunk_inflation_ratio: float  # chunk 与真实调用比值（如 450:1，量化防止的指标虚高膨胀倍数）
