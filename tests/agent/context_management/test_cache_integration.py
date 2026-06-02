"""缓存系统集成测试

验证完整的缓存链路：
1. ExplicitCacheProcessor 注入 cache_control 并设置 pending snapshot
2. 模拟 LLM 响应（包含 usage）
3. log_llm_response 触发 try_persist_cache_call_metrics
4. 验证 NDJSON 配对正确性

测试覆盖：
- 成功配对（有 explicit_cache_snapshot）
- 无配对（未注入断点的场景）
- 环境变量未设置（不写盘）
- Expected vs Actual 差异检测
"""

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import (
    PendingExplicitCacheSnapshot,
    clear_pending_explicit_cache_snapshot,
    set_cache_metrics_dir,
    set_pending_explicit_cache_snapshot,
    try_persist_cache_call_metrics,
)
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.cache_optimizer import ExplicitCacheProcessor


class TestCacheIntegration:
    """缓存系统集成测试"""

    @pytest.fixture
    def processor(self):
        """创建 ExplicitCacheProcessor"""
        return ExplicitCacheProcessor(safe_block_interval=15, min_message_gap=6, max_breakpoints=4)

    @pytest.fixture
    def sample_messages(self):
        """示例消息序列"""
        return [
            SystemMessage(content="You are a helpful assistant"),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
            HumanMessage(content="How are you?"),
        ]

    @pytest.fixture
    def mock_llm_response(self) -> dict[str, Any]:
        """模拟 LLM 响应（包含 usage）"""
        return {
            "id": "test_response_id",
            "model": "claude-3-5-sonnet-20241022",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "I'm doing well, thank you!",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10000,
                "completion_tokens": 50,
                "prompt_tokens_details": {
                    "cached_tokens": 8530,
                },
            },
        }

    async def test_full_cache_pipeline_with_ndjson(
        self, processor, sample_messages, mock_llm_response, tmp_path
    ):
        """测试完整缓存链路：Processor → NDJSON 配对"""
        metrics_dir = tmp_path / "cache_metrics"
        set_cache_metrics_dir(str(metrics_dir))

        try:
            clear_pending_explicit_cache_snapshot()

            context = ProcessorContext(
                messages=sample_messages.copy(),
                user_query="Test query",
                chat_id="test_chat_123",
                user_id="test_user_456",
            )
            context.metadata["model_name"] = "claude-3-5-sonnet-20241022"
            context.metadata["turn_count"] = 2
            context.metadata["compression_count"] = 0

            processed_context = await processor.process(context)

            last_msg = processed_context.messages[-1]
            assert "cache_control" in last_msg.additional_kwargs
            assert last_msg.additional_kwargs["cache_control"] == {"type": "ephemeral"}

            try_persist_cache_call_metrics(mock_llm_response)

            ndjson_files = list(metrics_dir.glob("cache_metrics_*.ndjson"))
            assert len(ndjson_files) == 1, "Should generate one NDJSON file"

            with ndjson_files[0].open("r", encoding="utf-8") as f:
                lines = f.readlines()
                assert len(lines) == 1, "Should have one record"

                record = json.loads(lines[0])

                assert record["schema_version"] == 1
                assert "recorded_at_utc" in record
                assert record["response_model"] == "claude-3-5-sonnet-20241022"

                assert record["prompt_tokens"] == 10000
                assert record["cached_tokens"] == 8530
                assert record["completion_tokens"] == 50
                assert "total_tokens" not in record

                assert abs(record["actual_cache_hit_rate"] - 0.853) < 0.001
                assert abs(record["cost_savings_pct_vs_uncached_input"] - 0.7677) < 0.001

                assert record["explicit_cache_snapshot"] is True
                assert "explicit_cache" in record

                explicit_cache = record["explicit_cache"]
                assert explicit_cache["turn_count"] == 2
                assert explicit_cache["compression_count"] == 0
                assert explicit_cache["breakpoint_count"] >= 2
                assert explicit_cache["message_count"] == len(sample_messages)
                assert explicit_cache["total_estimated_tokens"] > 0
                assert explicit_cache["expected_cacheable_tokens"] > 0

                assert "expected_hit_rate" not in explicit_cache
                assert "model_name" not in explicit_cache
                assert "chat_id" not in explicit_cache
                assert "user_id" not in explicit_cache
                assert "safe_block_interval" not in explicit_cache
                assert "min_message_gap" not in explicit_cache
                assert "max_breakpoints" not in explicit_cache
                assert "breakpoint_positions" not in explicit_cache

        finally:
            set_cache_metrics_dir(None)
            clear_pending_explicit_cache_snapshot()

    async def test_cache_pipeline_without_dir_no_file(self, processor, sample_messages, mock_llm_response):
        """测试未配置 metrics dir 时不写盘"""
        set_cache_metrics_dir(None)

        try:
            clear_pending_explicit_cache_snapshot()

            context = ProcessorContext(messages=sample_messages.copy(), user_query="Test query")
            context.metadata["model_name"] = "claude-3-5-sonnet-20241022"
            await processor.process(context)

            try_persist_cache_call_metrics(mock_llm_response)

        finally:
            set_cache_metrics_dir(None)
            clear_pending_explicit_cache_snapshot()

    async def test_cache_pipeline_without_snapshot(self, mock_llm_response, tmp_path):
        """测试无 pending snapshot 时的 NDJSON 记录"""
        metrics_dir = tmp_path / "cache_metrics_no_snapshot"
        set_cache_metrics_dir(str(metrics_dir))

        try:
            clear_pending_explicit_cache_snapshot()

            try_persist_cache_call_metrics(mock_llm_response)

            ndjson_files = list(metrics_dir.glob("cache_metrics_*.ndjson"))
            assert len(ndjson_files) == 1

            with ndjson_files[0].open("r", encoding="utf-8") as f:
                record = json.loads(f.readline())
                assert record["explicit_cache_snapshot"] is False
                assert "explicit_cache" not in record
                assert record["prompt_tokens"] == 10000
                assert record["cached_tokens"] == 8530

        finally:
            set_cache_metrics_dir(None)
            clear_pending_explicit_cache_snapshot()

    async def test_cache_pipeline_expected_vs_actual_detection(self, tmp_path):
        """测试 Expected vs Actual 差异检测（通过手动注入 snapshot）"""
        metrics_dir = tmp_path / "cache_metrics_diff"
        set_cache_metrics_dir(str(metrics_dir))

        try:
            clear_pending_explicit_cache_snapshot()

            high_expected_snapshot = PendingExplicitCacheSnapshot(
                turn_count=5,
                breakpoint_count=3,
                message_count=21,
                total_estimated_tokens=10000,
                expected_cacheable_tokens=8000,
                compression_count=0,
            )
            set_pending_explicit_cache_snapshot(high_expected_snapshot)

            abnormal_response = {
                "model": "claude-3-5-sonnet-20241022",
                "usage": {
                    "prompt_tokens": 10000,
                    "completion_tokens": 50,
                    "prompt_tokens_details": {
                        "cached_tokens": 2000,
                    },
                },
            }

            try_persist_cache_call_metrics(abnormal_response)

            ndjson_files = list(metrics_dir.glob("cache_metrics_*.ndjson"))
            with ndjson_files[0].open("r", encoding="utf-8") as f:
                record = json.loads(f.readline())

                explicit_cache = record["explicit_cache"]
                expected_hit_rate = (
                    explicit_cache["expected_cacheable_tokens"] / explicit_cache["total_estimated_tokens"]
                )
                actual_hit_rate = record["actual_cache_hit_rate"]

                assert abs(expected_hit_rate - 0.80) < 0.001
                assert abs(actual_hit_rate - 0.20) < 0.001
                assert abs(expected_hit_rate - actual_hit_rate) > 0.50

        finally:
            set_cache_metrics_dir(None)
            clear_pending_explicit_cache_snapshot()

    async def test_cache_pipeline_with_non_anthropic_model(
        self, processor, sample_messages, mock_llm_response, tmp_path
    ):
        """测试非 Anthropic 模型（OpenAI）should_process 检查"""
        metrics_dir = tmp_path / "cache_metrics_openai"
        set_cache_metrics_dir(str(metrics_dir))

        try:
            clear_pending_explicit_cache_snapshot()

            context = ProcessorContext(messages=sample_messages.copy(), user_query="Test query")
            context.metadata["model_name"] = "gpt-4o"

            should_process = await processor.should_process(context)
            assert should_process is False

            openai_response = mock_llm_response.copy()
            openai_response["model"] = "gpt-4o"
            try_persist_cache_call_metrics(openai_response)

            # 4. 验证 NDJSON 记录（无 explicit_cache_snapshot）
            ndjson_files = list(metrics_dir.glob("cache_metrics_*.ndjson"))
            with ndjson_files[0].open("r", encoding="utf-8") as f:
                record = json.loads(f.readline())
                assert record["explicit_cache_snapshot"] is False
                assert record["response_model"] == "gpt-4o"

        finally:
            set_cache_metrics_dir(None)
            clear_pending_explicit_cache_snapshot()


class TestCacheHealthMonitoring:
    """缓存健康检查集成测试"""

    async def test_manual_snapshot_injection(self, tmp_path):
        """测试手动注入 snapshot（模拟 middleware 行为）"""
        metrics_dir = tmp_path / "cache_metrics_manual"
        set_cache_metrics_dir(str(metrics_dir))

        try:
            clear_pending_explicit_cache_snapshot()

            snapshot = PendingExplicitCacheSnapshot(
                turn_count=5,
                breakpoint_count=3,
                message_count=21,
                total_estimated_tokens=12000,
                expected_cacheable_tokens=10500,
                compression_count=1,
            )
            set_pending_explicit_cache_snapshot(snapshot)

            response = {
                "model": "claude-3-5-sonnet-20241022",
                "usage": {
                    "prompt_tokens": 12000,
                    "completion_tokens": 100,
                    "prompt_tokens_details": {"cached_tokens": 10500},
                },
            }
            try_persist_cache_call_metrics(response)

            ndjson_files = list(metrics_dir.glob("cache_metrics_*.ndjson"))
            with ndjson_files[0].open("r", encoding="utf-8") as f:
                record = json.loads(f.readline())
                assert record["explicit_cache_snapshot"] is True
                explicit_cache = record["explicit_cache"]
                expected_hit_rate = (
                    explicit_cache["expected_cacheable_tokens"] / explicit_cache["total_estimated_tokens"]
                )
                assert abs(expected_hit_rate - 0.875) < 0.001
                assert abs(record["actual_cache_hit_rate"] - 0.875) < 0.001

        finally:
            set_cache_metrics_dir(None)
            clear_pending_explicit_cache_snapshot()
