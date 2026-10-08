"""Significance Gate ensuring only genuine life milestones are accepted.

Topic 01 Item 137: MilestoneSignificanceGate.
Prevents industrial trivia and transient code debug chores from polluting
decades-long human life timelines.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.toolkits.memory.life_milestones.models import (
    MilestoneCategory,
    PrivacyIntimacyLevel,
)


class GateVerificationResult(BaseModel):
    """Outcome of milestone intake verification."""

    model_config = ConfigDict(frozen=True)

    is_admitted: bool = Field(description="Whether milestone qualifies for admission")
    calculated_significance: float = Field(ge=0.0, le=1.0, description="Calculated life significance score")
    rejection_reason: str | None = Field(default=None, description="Reason if rejected")


class MilestoneSignificanceGate:
    """Evaluates candidate milestones to filter out low-significance industrial noise."""

    # Patterns indicating daily code tasks, debug chores, or ephemeral activities
    _INDUSTRIAL_TRIVIA_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(修复|fix|debug|refactor|重构).*?(bug|错误|样式|css|api|接口)", re.IGNORECASE),
        re.compile(r"(运行|执行|pass|fail).*?(单测|测试|test|pytest|ci|流水线)", re.IGNORECASE),
        re.compile(r"(更新|升级).*?(依赖|package|npm|pip|venv)", re.IGNORECASE),
        re.compile(r"(提交|commit|pr|pull request|git)", re.IGNORECASE),
        re.compile(r"(开会|daily standup|敏捷站会|周会|对齐)", re.IGNORECASE),
    )

    # Keywords that indicate meaningful human life transformations
    _LIFE_LANDMARK_KEYWORDS: tuple[str, ...] = (
        "毕业", "入学", "换城市", "搬家", "定居", "入职", "离职", "转行", "创业",
        "结婚", "订婚", "生子", "做父亲", "做母亲", "家人", "买房", "置业",
        "生病", "康复", "手术", "马拉松", "健身转型", "出版", "写书",
        "顿悟", "价值观", "转变", "初心", "告别", "相遇", "里程碑",
    )

    def __init__(self, min_significance_threshold: float = 0.70) -> None:
        self._min_threshold = min_significance_threshold

    def evaluate(
        self,
        title: str,
        narrative: str,
        category: MilestoneCategory,
        significance_hint: float = 0.80,
        is_user_explicit: bool = False,
        intimacy_level: PrivacyIntimacyLevel = PrivacyIntimacyLevel.OPEN_OVERVIEW,
    ) -> GateVerificationResult:
        """Verify whether an incoming candidate milestone belongs to a genuine life timeline."""
        title_stripped = title.strip()
        narrative_stripped = narrative.strip()
        full_text = f"{title_stripped} {narrative_stripped}"

        # 1. Basic length check
        if len(title_stripped) < 2:
            return GateVerificationResult(
                is_admitted=False,
                calculated_significance=0.0,
                rejection_reason="Title is too short to represent a life milestone.",
            )

        # 2. Rejection of industrial trivia
        for pattern in self._INDUSTRIAL_TRIVIA_PATTERNS:
            if pattern.search(full_text):
                # If user explicitly insists on recording an engineering milestone, only admit if tagged CAREER/PERSONAL_CREATIVE and high hint
                if is_user_explicit and category in (MilestoneCategory.CAREER, MilestoneCategory.PERSONAL_CREATIVE) and significance_hint >= 0.85:
                    break
                return GateVerificationResult(
                    is_admitted=False,
                    calculated_significance=0.2,
                    rejection_reason=f"Rejected as transient industrial trivia: matched '{pattern.pattern}'.",
                )

        # 3. Score calculation
        score = significance_hint

        # Boost score if life landmark keywords are explicitly present
        if any(kw in full_text for kw in self._LIFE_LANDMARK_KEYWORDS):
            score = min(1.0, score + 0.15)

        # Category weighting
        if category in (MilestoneCategory.FAMILY_LIFE, MilestoneCategory.VALUE_TRANSFORMATION, MilestoneCategory.RELOCATION):
            score = min(1.0, score + 0.1)

        # Explicit user input carries higher trust
        if is_user_explicit:
            score = max(score, 0.75)

        # 4. Final admission decision
        if score >= self._min_threshold:
            return GateVerificationResult(
                is_admitted=True,
                calculated_significance=round(score, 3),
                rejection_reason=None,
            )

        return GateVerificationResult(
            is_admitted=False,
            calculated_significance=round(score, 3),
            rejection_reason=f"Significance score {score:.2f} is below threshold {self._min_threshold:.2f}.",
        )
