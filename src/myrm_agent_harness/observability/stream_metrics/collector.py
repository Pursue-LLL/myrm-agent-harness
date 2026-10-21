"""
[INPUT]: Call sessions, incoming stream chunk deltas, and stream completion/error signals.
[OUTPUT]: Thread-safe StreamCallMetricsCollector managing call lifecycles and aggregating clean outcome metrics.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/stream_metrics/collector.py
"""

from datetime import datetime, timezone
import threading
import time
from typing import Dict, List, Optional

from .models import StreamCallOutcome, StreamCallSession, StreamMetricsAggregate


class StreamCallMetricsCollector:
    """流式调用按最终结果计量收集器（杜绝中间 chunk 污染指标）"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, StreamCallSession] = {}

    def start_call(
        self,
        call_id: str,
        model_name: str,
        provider: str = "openai",
    ) -> StreamCallSession:
        """开始一次流式调用的生命周期跟踪"""
        with self._lock:
            start_ms = time.time() * 1000.0
            session = StreamCallSession(
                call_id=call_id,
                model_name=model_name,
                provider=provider,
                start_time_ms=start_ms,
            )
            self._sessions[call_id] = session
            return session

    def record_chunk(
        self,
        call_id: str,
        chunk_tokens: int = 0,
        is_first_token: bool = False,
    ) -> Optional[StreamCallSession]:
        """记录中间 chunk 事件：仅统计累积数据与 TTFT，绝不增加独立调用次数"""
        with self._lock:
            session = self._sessions.get(call_id)
            if not session or session.is_finalized:
                return session

            session.chunk_count += 1
            session.total_tokens += max(0, chunk_tokens)

            # 记录首字生成时延 (TTFT)
            if is_first_token and session.ttft_ms is None:
                current_ms = time.time() * 1000.0
                session.ttft_ms = max(0.0, current_ms - session.start_time_ms)

            return session

    def finalize_call(
        self,
        call_id: str,
        outcome: StreamCallOutcome,
        error_message: Optional[str] = None,
    ) -> StreamCallSession:
        """幂等终态结算：仅在流结束时产生唯一一次调用归因记录"""
        with self._lock:
            session = self._sessions.get(call_id)
            if not session:
                # 若未显式 start 即已终态（如握手立即失败），自动创建一次异常 session
                start_ms = time.time() * 1000.0
                session = StreamCallSession(
                    call_id=call_id,
                    model_name="unknown",
                    provider="unknown",
                    start_time_ms=start_ms,
                )
                self._sessions[call_id] = session

            if session.is_finalized:
                return session

            end_ms = time.time() * 1000.0
            session.end_time_ms = end_ms
            session.total_duration_ms = max(0.0, end_ms - session.start_time_ms)
            session.outcome = outcome
            session.error_message = error_message
            session.is_finalized = True

            # 若未曾收到任何 chunk 却成功完成，赋予默认 0 TTFT
            if session.ttft_ms is None:
                session.ttft_ms = session.total_duration_ms

            return session

    def get_session(self, call_id: str) -> Optional[StreamCallSession]:
        """查询特定调用的跟踪会话"""
        with self._lock:
            return self._sessions.get(call_id)

    def get_aggregate(
        self,
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> StreamMetricsAggregate:
        """获取按最终结果结算的真实度量大盘（排除了中间 Chunk 虚高膨胀）"""
        with self._lock:
            candidates: List[StreamCallSession] = [
                s for s in self._sessions.values() if s.is_finalized
            ]
            if model_name:
                candidates = [s for s in candidates if s.model_name == model_name]
            if provider:
                candidates = [s for s in candidates if s.provider == provider]

            total_calls = len(candidates)
            success_calls = sum(
                1 for s in candidates if s.outcome == StreamCallOutcome.SUCCESS
            )
            error_calls = sum(
                1 for s in candidates if s.outcome == StreamCallOutcome.ERROR
            )
            cancelled_calls = sum(
                1 for s in candidates if s.outcome == StreamCallOutcome.CANCELLED
            )
            timeout_calls = sum(
                1 for s in candidates if s.outcome == StreamCallOutcome.TIMEOUT
            )

            total_chunks = sum(s.chunk_count for s in candidates)
            total_tokens = sum(s.total_tokens for s in candidates)

            ttft_list = [
                s.ttft_ms for s in candidates if s.ttft_ms is not None
            ]
            avg_ttft_ms = (
                sum(ttft_list) / len(ttft_list) if ttft_list else 0.0
            )

            duration_list = [
                s.total_duration_ms for s in candidates if s.total_duration_ms is not None
            ]
            avg_duration_ms = (
                sum(duration_list) / len(duration_list) if duration_list else 0.0
            )

            success_rate = (
                (success_calls / total_calls * 100.0) if total_calls > 0 else 0.0
            )
            inflation_ratio = (
                (total_chunks / total_calls) if total_calls > 0 else 1.0
            )

            return StreamMetricsAggregate(
                total_calls=total_calls,
                success_calls=success_calls,
                error_calls=error_calls,
                cancelled_calls=cancelled_calls,
                timeout_calls=timeout_calls,
                total_chunks=total_chunks,
                total_tokens=total_tokens,
                avg_ttft_ms=round(avg_ttft_ms, 2),
                avg_duration_ms=round(avg_duration_ms, 2),
                success_rate_pct=round(success_rate, 2),
                chunk_inflation_ratio=round(inflation_ratio, 2),
            )

    def reset(self) -> None:
        """重置所有收集会话（主要用于单元测试隔离）"""
        with self._lock:
            self._sessions.clear()
