"""Active ambiguity detector identifying under-specified, multi-path, or risky instructions.

Analyzes raw user instructions against destructive boundaries, missing parameters,
and architectural divergence, generating proactive ClarifyTool invocation blueprints.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.clarify.clarify_tool_types import (
    AmbiguityCategory,
    AmbiguityDetectionReport,
    ClarifyOptionItem,
    ClarifyToolParams,
    ImpactLevelKind,
)

_DESTRUCTIVE_KEYWORDS: tuple[str, ...] = (
    "rm -rf",
    "delete all",
    "drop database",
    "drop table",
    "删除所有",
    "清空",
    "清理无用",
    "全部删除",
    "purge cache",
    "hard reset",
)

_MISSING_PARAM_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("备份", "目标目录与备份格式未指定", ("创建带时间戳的本地 tar.gz", "同步至临时存储区", "先打印备份清单确认")),
    ("导出", "导出目标路径与格式未指定", ("导出为 JSON 格式", "导出为 CSV/Excel 格式", "导出为 Markdown 汇总")),
    ("打包发布", "目标发布环境与版本号未指定", ("打测试 Release 预览包", "发布到本地 Staging", "询问版本号后再打包")),
)

_ARCH_CHOICE_KEYWORDS: tuple[str, ...] = (
    "重构架构",
    "优化性能",
    "升级技术栈",
    "改用最新方案",
    "彻底重写",
)


class ActiveAmbiguityDetector:
    """Proactively detects instructional ambiguities before model execution."""

    def analyze_instruction(
        self,
        instruction: str,
        context_metadata: dict[str, str] | None = None,
    ) -> AmbiguityDetectionReport:
        """Analyze natural language instruction for destructive risks or missing parameters."""
        text = instruction.strip().lower()

        # 1. Check Destructive Risk Boundary
        for kw in _DESTRUCTIVE_KEYWORDS:
            if kw in text:
                options = (
                    ClarifyOptionItem(
                        option_id="opt_dry_run",
                        label="仅模拟演练（Dry-Run）",
                        description="只打印将被影响的文件/数据清单，不执行物理删除",
                        is_recommended=True,
                    ),
                    ClarifyOptionItem(
                        option_id="opt_backup_first",
                        label="自动创建物理备份后继续",
                        description="在系统临时目录备份受影响文件后再安全删除",
                        is_recommended=False,
                    ),
                    ClarifyOptionItem(
                        option_id="opt_abort",
                        label="取消破坏性操作",
                        description="完全终止该指令，保持现状",
                        is_recommended=False,
                    ),
                )
                suggested_params = ClarifyToolParams(
                    question=f"检测到高危潜在破坏性指令（包含 '{kw}'），请确认执行策略：",
                    options=options,
                    allow_custom_input=True,
                    allow_multiple=False,
                    impact_level=ImpactLevelKind.CRITICAL_DESTRUCTIVE,
                    category=AmbiguityCategory.DESTRUCTIVE_BOUNDARY,
                )
                return AmbiguityDetectionReport(
                    is_ambiguous=True,
                    category=AmbiguityCategory.DESTRUCTIVE_BOUNDARY,
                    confidence=0.95,
                    missing_elements=("explicit_scope_confirmation", "safety_backup_preference"),
                    suggested_clarify_params=suggested_params,
                )

        # 2. Check Missing Crucial Parameters
        for trigger, missing_desc, choices in _MISSING_PARAM_PATTERNS:
            if trigger in instruction:
                # Check if specific target format or path is already supplied
                has_path = bool(re.search(r"/[a-zA-Z0-9_.-]+|\.zip|\.json|\.tar", instruction))
                if not has_path:
                    options = tuple(
                        ClarifyOptionItem(
                            option_id=f"opt_param_{idx}",
                            label=choice,
                            is_recommended=(idx == 0),
                        )
                        for idx, choice in enumerate(choices)
                    )
                    suggested_params = ClarifyToolParams(
                        question=f"执行 '{trigger}' 任务需要明确具体格式与路径，请选择：",
                        options=options,
                        allow_custom_input=True,
                        allow_multiple=False,
                        impact_level=ImpactLevelKind.MEDIUM,
                        category=AmbiguityCategory.MISSING_PARAMETER,
                    )
                    return AmbiguityDetectionReport(
                        is_ambiguous=True,
                        category=AmbiguityCategory.MISSING_PARAMETER,
                        confidence=0.88,
                        missing_elements=(missing_desc,),
                        suggested_clarify_params=suggested_params,
                    )

        # 3. Check Multiple Architectural Approaches
        for kw in _ARCH_CHOICE_KEYWORDS:
            if kw in instruction:
                options = (
                    ClarifyOptionItem(
                        option_id="opt_conservative",
                        label="保守重构（保持公共接口与外部行为严格不变）",
                        description="最小化变更面，优先编写回归测试保障零破坏",
                        is_recommended=True,
                    ),
                    ClarifyOptionItem(
                        option_id="opt_clean_rewrite",
                        label="激进纯净重构（不考虑向后兼容，追求最优架构）",
                        description="彻底重构类型系统与模块划分，消除历史技术债",
                        is_recommended=False,
                    ),
                )
                suggested_params = ClarifyToolParams(
                    question=f"针对 '{kw}' 任务，存在不同的架构路线，请选择优先方向：",
                    options=options,
                    allow_custom_input=True,
                    allow_multiple=False,
                    impact_level=ImpactLevelKind.HIGH,
                    category=AmbiguityCategory.MULTIPLE_APPROACHES,
                )
                return AmbiguityDetectionReport(
                    is_ambiguous=True,
                    category=AmbiguityCategory.MULTIPLE_APPROACHES,
                    confidence=0.82,
                    missing_elements=("architectural_direction", "backward_compatibility_policy"),
                    suggested_clarify_params=suggested_params,
                )

        # Instruction is self-contained and clear
        return AmbiguityDetectionReport(
            is_ambiguous=False,
            category=AmbiguityCategory.USER_PREFERENCE,
            confidence=0.0,
            missing_elements=(),
            suggested_clarify_params=None,
        )
