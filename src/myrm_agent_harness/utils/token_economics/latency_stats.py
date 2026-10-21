"""LLM 调用延迟统计

[INPUT]
- (none)

[OUTPUT]
- LatencyStats: 延迟统计 frozen dataclass（avg_ms, p95_ms, min_ms, max_ms, avg_ttft_ms, p95_ttft_ms, avg_tokens_per_second）
  - from_samples(): 由逐次调用的耗时与首 token 耗时样本汇总

[POS]
Pure statistics over the per-call samples a ``TokenTracker`` collects; keeps ``tracker.py`` on accumulation and the request-scoped API.
"""

from dataclasses import dataclass


def _percentile(sorted_data: list[float], p: float) -> float:
    """Compute percentile from sorted data."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


@dataclass(frozen=True)
class LatencyStats:
    """LLM 调用延迟统计"""

    call_count: int = 0
    avg_ms: float = 0.0
    p95_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    avg_ttft_ms: float = 0.0
    p95_ttft_ms: float = 0.0
    avg_tokens_per_second: float = 0.0

    @classmethod
    def from_samples(
        cls,
        durations_ms: list[float],
        ttft_ms: list[float],
        completion_tokens: int,
    ) -> "LatencyStats":
        """Summarize call durations and time-to-first-token samples (all in milliseconds)."""
        if not durations_ms:
            return cls()

        sorted_durations = sorted(durations_ms)
        sorted_ttft = sorted(ttft_ms)

        total_duration_s = sum(durations_ms) / 1000.0
        avg_tps = completion_tokens / total_duration_s if total_duration_s > 0 else 0.0

        return cls(
            call_count=len(sorted_durations),
            avg_ms=sum(sorted_durations) / len(sorted_durations),
            p95_ms=_percentile(sorted_durations, 0.95),
            min_ms=sorted_durations[0],
            max_ms=sorted_durations[-1],
            avg_ttft_ms=(sum(sorted_ttft) / len(sorted_ttft) if sorted_ttft else 0.0),
            p95_ttft_ms=_percentile(sorted_ttft, 0.95),
            avg_tokens_per_second=round(avg_tps, 1),
        )
