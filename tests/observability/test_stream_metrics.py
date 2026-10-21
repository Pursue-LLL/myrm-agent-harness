"""
[INPUT]:
- myrm_agent_harness.observability.stream_metrics::*

[OUTPUT]:
- Pytest verification for streamed calls final outcome metrics, chunk anti-pollution guarantees, and TTFT tracking.

[POS]:
tests/observability/test_stream_metrics.py — 流式调用按最终结果计量（中间事件不污染指标）单元测试。
"""

import time
import pytest

from myrm_agent_harness.observability.stream_metrics import (
    StreamCallOutcome,
    StreamCallMetricsCollector,
)


def test_streamed_call_single_outcome_not_polluted_by_chunks() -> None:
    collector = StreamCallMetricsCollector()
    call_id = "call_stream_clean_001"

    # 1. 发起流式调用
    session = collector.start_call(
        call_id=call_id,
        model_name="claude-3-7-sonnet-20250219",
        provider="anthropic",
    )
    assert session.call_id == call_id
    assert session.chunk_count == 0
    assert session.is_finalized is False

    # 2. 模拟 300 个中间流式 chunk（中间包含首字 token 标记）
    time.sleep(0.01)  # 模拟微小延迟
    collector.record_chunk(call_id, chunk_tokens=2, is_first_token=True)

    for i in range(299):
        collector.record_chunk(call_id, chunk_tokens=3, is_first_token=False)

    # 在 finalize 前，聚合大盘中不应包含未结算的半成品调用
    agg_in_flight = collector.get_aggregate()
    assert agg_in_flight.total_calls == 0

    # 3. 正常完成流式生成结算为 SUCCESS
    final_session = collector.finalize_call(call_id, outcome=StreamCallOutcome.SUCCESS)
    assert final_session.is_finalized is True
    assert final_session.outcome == StreamCallOutcome.SUCCESS
    assert final_session.chunk_count == 300
    assert final_session.total_tokens == (2 + 299 * 3)
    assert final_session.ttft_ms is not None
    assert final_session.ttft_ms >= 5.0  # 刚才 sleep 了 10ms

    # 4. 关键验证：大盘总调用数必须严格为 1，绝对不能被 300 个 chunk 虚高膨胀为 300！
    agg = collector.get_aggregate()
    assert agg.total_calls == 1
    assert agg.success_calls == 1
    assert agg.error_calls == 0
    assert agg.total_chunks == 300
    assert agg.total_tokens == (2 + 299 * 3)
    assert agg.success_rate_pct == 100.0
    assert agg.chunk_inflation_ratio == 300.0


def test_streamed_call_cancellation_error_and_timeout_attribution() -> None:
    collector = StreamCallMetricsCollector()

    # Call 1: 用户主动取消 (CANCELLED)
    c1 = "call_cancelled_01"
    collector.start_call(c1, model_name="gpt-4o", provider="openai")
    collector.record_chunk(c1, chunk_tokens=5, is_first_token=True)
    collector.record_chunk(c1, chunk_tokens=5)
    collector.finalize_call(c1, outcome=StreamCallOutcome.CANCELLED)

    # Call 2: 首字等待超时 (TIMEOUT)
    c2 = "call_timeout_02"
    collector.start_call(c2, model_name="gpt-4o", provider="openai")
    collector.finalize_call(c2, outcome=StreamCallOutcome.TIMEOUT, error_message="Connect timeout after 15s")

    # Call 3: 中途中断报错 (ERROR)
    c3 = "call_error_03"
    collector.start_call(c3, model_name="deepseek-v3", provider="deepseek")
    collector.record_chunk(c3, chunk_tokens=10, is_first_token=True)
    collector.finalize_call(c3, outcome=StreamCallOutcome.ERROR, error_message="Stream dropped by peer")

    # Call 4: 正常成功 (SUCCESS)
    c4 = "call_success_04"
    collector.start_call(c4, model_name="deepseek-v3", provider="deepseek")
    collector.record_chunk(c4, chunk_tokens=20, is_first_token=True)
    collector.finalize_call(c4, outcome=StreamCallOutcome.SUCCESS)

    # 聚合总览 (共 4 次独立调用，包含 1 成功、1 取消、1 超时、1 失败)
    agg_all = collector.get_aggregate()
    assert agg_all.total_calls == 4
    assert agg_all.success_calls == 1
    assert agg_all.cancelled_calls == 1
    assert agg_all.timeout_calls == 1
    assert agg_all.error_calls == 1
    assert agg_all.success_rate_pct == 25.0

    # 按模型筛选
    agg_ds = collector.get_aggregate(model_name="deepseek-v3")
    assert agg_ds.total_calls == 2
    assert agg_ds.success_calls == 1
    assert agg_ds.error_calls == 1
    assert agg_ds.success_rate_pct == 50.0

    # 幂等性验证：重复调用 finalize_call 不应改变统计结果
    collector.finalize_call(c4, outcome=StreamCallOutcome.ERROR)  # 已 finalized，忽略
    agg_after_idempotent = collector.get_aggregate(model_name="deepseek-v3")
    assert agg_after_idempotent.success_calls == 1
    assert agg_after_idempotent.error_calls == 1
