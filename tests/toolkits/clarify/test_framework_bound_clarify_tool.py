"""Unit tests for framework-bound ClarifyTool and active ambiguity detector.

Validates proactive detection of destructive risks, missing parameter blueprints,
standardized JSON Schema declarations, A2UI card generation, and interactive resolution formatting.
"""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.toolkits.clarify.active_ambiguity_detector import (
    ActiveAmbiguityDetector,
)
from myrm_agent_harness.toolkits.clarify.clarify_tool_types import (
    AmbiguityCategory,
    ClarifyOptionItem,
    ClarifyResolutionResult,
    ClarifyToolParams,
    ImpactLevelKind,
)
from myrm_agent_harness.toolkits.clarify.framework_bound_clarify_tool import (
    FrameworkBoundClarifyTool,
)


@pytest.mark.asyncio
async def test_active_ambiguity_detector_destructive_boundary() -> None:
    """Validate that hazardous destructive instructions trigger critical ambiguity report."""
    detector = ActiveAmbiguityDetector()

    report = detector.analyze_instruction("帮我清理无用数据并删除所有缓存记录")
    assert report.is_ambiguous is True
    assert report.category == AmbiguityCategory.DESTRUCTIVE_BOUNDARY
    assert report.confidence >= 0.90
    assert report.suggested_clarify_params is not None
    assert (
        report.suggested_clarify_params.impact_level
        == ImpactLevelKind.CRITICAL_DESTRUCTIVE
    )

    options = report.suggested_clarify_params.options
    assert len(options) >= 2
    # Ensure dry run option is recommended by default
    assert any(opt.is_recommended and "dry_run" in opt.option_id for opt in options)


@pytest.mark.asyncio
async def test_active_ambiguity_detector_missing_parameters() -> None:
    """Validate that ambiguous instructions lacking target formats generate structured options."""
    detector = ActiveAmbiguityDetector()

    report = detector.analyze_instruction("请把这个项目的报表导出一下")
    assert report.is_ambiguous is True
    assert report.category == AmbiguityCategory.MISSING_PARAMETER
    assert report.suggested_clarify_params is not None
    assert report.suggested_clarify_params.impact_level == ImpactLevelKind.MEDIUM

    options = report.suggested_clarify_params.options
    assert len(options) == 3
    assert any("JSON" in opt.label for opt in options)
    assert any("CSV" in opt.label for opt in options)


@pytest.mark.asyncio
async def test_active_ambiguity_detector_clear_instruction() -> None:
    """Validate that unambiguous and specific instructions pass without false-positive gating."""
    detector = ActiveAmbiguityDetector()

    report = detector.analyze_instruction(
        "在 math_utils.py 中编写一个计算余弦相似度的纯函数，输入为两个 list[float]"
    )
    assert report.is_ambiguous is False
    assert report.confidence == 0.0
    assert report.suggested_clarify_params is None


@pytest.mark.asyncio
async def test_framework_bound_clarify_tool_declaration_and_a2ui_card() -> None:
    """Validate standard tool schema declaration and A2UI interactive card formatting."""
    tool = FrameworkBoundClarifyTool()

    # Check declaration
    decl = tool.get_tool_declaration()
    assert decl["name"] == "clarify_tool"
    assert "parameters" in decl
    assert "properties" in decl["parameters"]  # type: ignore[operator]

    # Format card payload
    params = ClarifyToolParams(
        question="请选择用于持久化的底层数据库：",
        options=(
            ClarifyOptionItem(
                option_id="opt_sqlite",
                label="SQLite（轻量嵌入式）",
                description="单文件零配置，适合本地单机与开发联调",
                is_recommended=True,
            ),
            ClarifyOptionItem(
                option_id="opt_postgres",
                label="PostgreSQL（高并发企业级）",
                description="适合云端高并发生产环境",
                is_recommended=False,
            ),
        ),
        allow_custom_input=True,
        impact_level=ImpactLevelKind.MEDIUM,
        category=AmbiguityCategory.MULTIPLE_APPROACHES,
    )

    card = tool.format_a2ui_card(params)
    assert card["component"] == "ClarifyQuestionCard"
    assert card["impactLevel"] == "medium"
    assert card["category"] == "multiple_approaches"
    assert len(card["options"]) == 2  # type: ignore[arg-type]

    # Without resolution handler, execution outputs json card string
    raw_output = tool.execute(params)
    parsed = json.loads(raw_output)
    assert parsed["component"] == "ClarifyQuestionCard"
    assert parsed["question"] == params.question


@pytest.mark.asyncio
async def test_clarify_tool_interactive_execution_and_result_formatting() -> None:
    """Validate interactive confirmation handling producing deterministic tool outputs."""
    tool = FrameworkBoundClarifyTool()

    params = ClarifyToolParams(
        question="检测到旧依赖冲突，请选择升级方案：",
        options=(
            ClarifyOptionItem(option_id="opt_safe", label="保守兼容模式", is_recommended=True),
            ClarifyOptionItem(option_id="opt_upgrade", label="升级到最新版本", is_recommended=False),
        ),
        impact_level=ImpactLevelKind.HIGH,
    )

    def mock_user_response(p: ClarifyToolParams) -> ClarifyResolutionResult:
        return tool.create_automated_resolution(
            p,
            selected_option_id="opt_safe",
            custom_input="优先保障既有测试通过",
        )

    output = tool.execute(params, resolution_handler=mock_user_response)
    assert "User clarified and selected: [保守兼容模式]" in output
    assert "Custom note: '优先保障既有测试通过'" in output
    assert "Proceed strictly adhering to this choice" in output
