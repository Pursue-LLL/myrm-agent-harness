"""Unit tests for In-Context Next Action and Question Predictor.

Verifies artifact-aware deterministic heuristics, conversational pattern detection,
deduplication, limits, and resilient async blending with timeout fallback.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.runtime.context.artifact_heuristic_rule_engine import (
    ArtifactHeuristicRuleEngine,
)
from myrm_agent_harness.runtime.context.in_context_next_action_predictor import (
    InContextNextActionPredictor,
)
from myrm_agent_harness.runtime.context.next_action_predictor_types import (
    ActionIntentType,
    NextActionPredictorConfig,
    PredictedActionChip,
    PredictionContextInput,
    TurnExecutionArtifact,
)


def test_code_modified_without_tests_generates_verification_chip() -> None:
    """Verifies that unverified code changes trigger high-priority test recommendations."""
    predictor = InContextNextActionPredictor()
    ctx = PredictionContextInput(
        session_id="sess_code_edit",
        last_user_query="请重构用户认证模块",
        last_assistant_reply="已经更新了 auth.py 模块，调整了令牌解析逻辑。",
        artifact=TurnExecutionArtifact(
            modified_files=["src/auth/service.py"],
            executed_commands=[],
            test_passed=None,
        ),
    )

    report = predictor.predict_sync(ctx)

    assert report.session_id == "sess_code_edit"
    assert report.has_test_recommendation is True
    assert len(report.chips) >= 2

    top_chip = report.chips[0]
    assert top_chip.intent == ActionIntentType.TEST_VERIFICATION
    assert top_chip.target_resource == "src/auth/service.py"
    assert top_chip.confidence >= 0.9
    assert "测试" in top_chip.label


def test_execution_failure_triggers_bug_fix_chip() -> None:
    """Verifies that runtime error or failing tests surface a top-priority fix chip."""
    predictor = InContextNextActionPredictor()
    ctx = PredictionContextInput(
        session_id="sess_error_recovery",
        last_user_query="运行测试套件",
        last_assistant_reply="测试执行失败，断言返回状态码 500。",
        artifact=TurnExecutionArtifact(
            modified_files=["src/api/handler.py"],
            executed_commands=["pytest tests/api/"],
            test_passed=False,
            has_error=True,
            error_excerpt="AssertionError: assert 500 == 200 in test_post_user",
        ),
    )

    report = predictor.predict_sync(ctx)

    top_chip = report.chips[0]
    assert top_chip.intent == ActionIntentType.BUG_FIX
    assert top_chip.confidence >= 0.95
    assert "修复" in top_chip.label
    assert "test_post_user" in top_chip.prompt or "500 == 200" in top_chip.prompt


def test_build_config_file_triggers_build_validation_chip() -> None:
    """Verifies that updating configuration files suggests local build verification."""
    engine = ArtifactHeuristicRuleEngine()
    ctx = PredictionContextInput(
        session_id="sess_cfg_edit",
        last_user_query="升级依赖版本",
        last_assistant_reply="已更新 pyproject.toml 中的 pydantic 依赖。",
        artifact=TurnExecutionArtifact(
            modified_files=["pyproject.toml"],
            executed_commands=["poetry lock"],
            test_passed=True,
        ),
    )

    chips = engine.evaluate(ctx)
    build_chips = [c for c in chips if c.intent == ActionIntentType.BUILD_DEPLOY]

    assert len(build_chips) == 1
    assert build_chips[0].target_resource == "pyproject.toml"
    assert "构建" in build_chips[0].label


def test_pure_conversational_and_fallback_resilience() -> None:
    """Verifies that conversational queries trigger inquiry chips and empty input has fallbacks."""
    predictor = InContextNextActionPredictor(
        config=NextActionPredictorConfig(max_chips=3)
    )

    # 1. Architectural discussion inquiry
    arch_ctx = PredictionContextInput(
        session_id="sess_arch_chat",
        last_user_query="请帮我设计一个低延迟分层缓存架构",
        last_assistant_reply="我们可以将本地内存缓存与分布式 Redis 结合，并利用版本号防击穿。",
        artifact=None,
    )
    arch_report = predictor.predict_sync(arch_ctx)
    assert len(arch_report.chips) >= 2
    assert any(c.intent == ActionIntentType.DEEPEN_INQUIRY for c in arch_report.chips)

    # 2. Resilient fallback for minimal input
    empty_ctx = PredictionContextInput(
        session_id="sess_empty",
        last_user_query="你好",
        last_assistant_reply="你好，请问有什么可以帮您？",
        artifact=None,
    )
    empty_report = predictor.predict_sync(empty_ctx)
    assert len(empty_report.chips) >= 1
    assert empty_report.fallback_used is False


@pytest.mark.asyncio
async def test_async_llm_blending_and_timeout_fallback() -> None:
    """Verifies async blending with external LLM and graceful fallback on timeout."""
    async def mock_llm_ok(
        ctx: PredictionContextInput,
    ) -> list[PredictedActionChip]:
        return [
            PredictedActionChip(
                chip_id="llm_custom_action",
                intent=ActionIntentType.CUSTOM_ACTION,
                label="生成 OpenAPI 文档规范",
                prompt="请依据当前路由定义导出最新的 openapi.json 文档。",
                confidence=0.99,
            )
        ]

    predictor_ok = InContextNextActionPredictor(
        config=NextActionPredictorConfig(max_chips=2),
        llm_predictor=mock_llm_ok,
    )
    ctx = PredictionContextInput(
        session_id="sess_async_blend",
        last_user_query="接口编写完成",
        last_assistant_reply="接口实现已就绪。",
        artifact=TurnExecutionArtifact(
            modified_files=["src/routes/api.py"],
            executed_commands=["pytest"],
            test_passed=True,
        ),
    )

    report = await predictor_ok.predict_async(ctx)
    assert report.engine_source == "blended_heuristic_and_llm"
    assert report.fallback_used is False
    assert report.chips[0].chip_id == "llm_custom_action"
    assert len(report.chips) <= 2

    # Timeout fallback simulation
    async def mock_llm_timeout(
        ctx: PredictionContextInput,
    ) -> list[PredictedActionChip]:
        await asyncio.sleep(0.5)
        return []

    predictor_timeout = InContextNextActionPredictor(
        llm_predictor=mock_llm_timeout,
    )
    fallback_report = await predictor_timeout.predict_async(ctx, timeout_seconds=0.05)
    assert fallback_report.fallback_used is True
    assert len(fallback_report.chips) > 0
