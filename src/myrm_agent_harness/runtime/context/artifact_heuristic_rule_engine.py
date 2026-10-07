"""Artifact-aware heuristic rule engine for next action prediction.

Evaluates observed code modifications, test execution results, errors,
and conversation intent patterns to derive high-confidence actionable chips.

[INPUT]
- runtime.context.next_action_predictor_types::ActionIntentType, PredictedActionChip,
  PredictionContextInput, TurnExecutionArtifact (POS: Types and data contracts for In-Context Next Action
  and Question Predictor.)

[OUTPUT]
- ArtifactHeuristicRuleEngine: Deterministic heuristic generator deriving actionable chips from execution
  facts.

[POS]
Artifact-aware heuristic rule engine for next action prediction.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.next_action_predictor_types import (
    ActionIntentType,
    PredictedActionChip,
    PredictionContextInput,
    TurnExecutionArtifact,
)

_CODE_EXTENSIONS: tuple[str, ...] = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".cs",
)
_BUILD_CONFIG_FILES: tuple[str, ...] = (
    "package.json",
    "pyproject.toml",
    "setup.py",
    "cargo.toml",
    "dockerfile",
    "vite.config.ts",
    "tsconfig.json",
    "go.mod",
)
_TEST_COMMAND_PATTERNS: tuple[str, ...] = (
    "pytest",
    "npm test",
    "vitest",
    "cargo test",
    "go test",
    "jest",
    "make test",
)


class ArtifactHeuristicRuleEngine:
    """Deterministic heuristic generator deriving actionable chips from execution facts."""

    def evaluate(self, ctx: PredictionContextInput) -> list[PredictedActionChip]:
        """Generate categorized candidate action chips from context input."""
        chips: list[PredictedActionChip] = []
        artifact = ctx.artifact

        if artifact is not None:
            chips.extend(self._evaluate_artifact_signals(artifact))

        if len(chips) < 2:
            chips.extend(self._evaluate_conversational_signals(ctx))

        if not chips:
            chips.extend(self._generate_fallback_chips())

        return chips

    def _evaluate_artifact_signals(
        self, artifact: TurnExecutionArtifact
    ) -> list[PredictedActionChip]:
        """Derive chips by analyzing concrete execution artifacts and exit statuses."""
        results: list[PredictedActionChip] = []

        # 1. Error / Test Failure signal has top priority
        if artifact.has_error or artifact.test_passed is False:
            detail = ""
            if artifact.error_excerpt:
                clean_err = re.sub(r"\s+", " ", artifact.error_excerpt).strip()
                detail = f": {clean_err[:120]}"
            results.append(
                PredictedActionChip(
                    chip_id="action_fix_error",
                    intent=ActionIntentType.BUG_FIX,
                    label="修复执行报错与根因",
                    prompt=f"排查并修复上一轮执行遇到的错误与断言失败{detail}，确保逻辑正确恢复。",
                    confidence=0.98,
                    icon_hint="wrench",
                    metadata={"error_flag": "true"},
                )
            )

        # 2. Source code modification without running tests
        code_files = [
            f for f in artifact.modified_files if f.lower().endswith(_CODE_EXTENSIONS)
        ]
        has_run_tests = any(
            any(pat in cmd.lower() for pat in _TEST_COMMAND_PATTERNS)
            for cmd in artifact.executed_commands
        ) or (artifact.test_passed is True)

        if code_files and not has_run_tests:
            sample_target = code_files[0]
            results.append(
                PredictedActionChip(
                    chip_id="action_run_verification_tests",
                    intent=ActionIntentType.TEST_VERIFICATION,
                    label="运行测试验证改动",
                    prompt=f"运行受影响的单元测试或回归测试，验证 {sample_target} 及相关改动的正确性。",
                    target_resource=sample_target,
                    confidence=0.95,
                    icon_hint="check-circle",
                    metadata={"modified_code_count": str(len(code_files))},
                )
            )

        # 3. Source code modification review
        if artifact.modified_files:
            results.append(
                PredictedActionChip(
                    chip_id="action_review_git_diff",
                    intent=ActionIntentType.CODE_REVIEW,
                    label="审查代码差异与质量",
                    prompt="检查当前工作区 git diff 变动，确保遵循架构规范、无冗余代码与 lint 警告。",
                    confidence=0.88,
                    icon_hint="git-branch",
                    metadata={"total_modified": str(len(artifact.modified_files))},
                )
            )

        # 4. Build or config file changed
        config_files = [
            f
            for f in artifact.modified_files
            if any(cfg in f.lower() for cfg in _BUILD_CONFIG_FILES)
        ]
        if config_files:
            results.append(
                PredictedActionChip(
                    chip_id="action_verify_build",
                    intent=ActionIntentType.BUILD_DEPLOY,
                    label="执行本地构建校验",
                    prompt=f"针对已修改的配置文件 {config_files[0]} 执行构建或依赖安装校验，确保工程完整可用。",
                    target_resource=config_files[0],
                    confidence=0.85,
                    icon_hint="box",
                    metadata={"config_file": config_files[0]},
                )
            )

        return results

    def _evaluate_conversational_signals(
        self, ctx: PredictionContextInput
    ) -> list[PredictedActionChip]:
        """Derive chips by analyzing recent dialogue themes and query semantics."""
        results: list[PredictedActionChip] = []
        combined_text = f"{ctx.last_user_query} {ctx.last_assistant_reply}".lower()

        # Architecture / Design exploration
        if any(kw in combined_text for kw in ("架构", "设计", "方案", "选型", "重构")):
            results.append(
                PredictedActionChip(
                    chip_id="action_deepen_architecture",
                    intent=ActionIntentType.DEEPEN_INQUIRY,
                    label="细化架构与模块接口",
                    prompt="进一步细化该方案的核心模块边界、接口契约及关键依赖，评估潜在演进风险。",
                    confidence=0.82,
                    icon_hint="layers",
                )
            )
            results.append(
                PredictedActionChip(
                    chip_id="action_plan_implementation",
                    intent=ActionIntentType.CUSTOM_ACTION,
                    label="制定分步执行计划",
                    prompt="请列出落地此方案的分步实施计划与里程碑，按优先级推进编码实现。",
                    confidence=0.80,
                    icon_hint="list-ordered",
                )
            )

        # Analysis / explanation inquiry
        elif any(kw in combined_text for kw in ("为什么", "原理", "机制", "对比")):
            results.append(
                PredictedActionChip(
                    chip_id="action_explore_tradeoffs",
                    intent=ActionIntentType.DEEPEN_INQUIRY,
                    label="对比备选方案利弊",
                    prompt="对比其他常见技术选型或替代方案的优缺点，从性能、易用性和维护成本进行权衡。",
                    confidence=0.78,
                    icon_hint="compass",
                )
            )

        return results

    def _generate_fallback_chips(self) -> Sequence[PredictedActionChip]:
        """Ensure resilient chips are always available if no specific rules trigger."""
        return (
            PredictedActionChip(
                chip_id="action_summarize_and_next",
                intent=ActionIntentType.CUSTOM_ACTION,
                label="总结进展并建议下一步",
                prompt="总结当前会话取得的关键成果与未决事项，并给出下一步最优行动建议。",
                confidence=0.72,
                icon_hint="arrow-right",
            ),
            PredictedActionChip(
                chip_id="action_run_diagnostics",
                intent=ActionIntentType.TEST_VERIFICATION,
                label="检查环境与代码健康度",
                prompt="全面运行代码规范检查与单元测试套件，确认当前仓库健康度良好。",
                confidence=0.68,
                icon_hint="activity",
            ),
        )
