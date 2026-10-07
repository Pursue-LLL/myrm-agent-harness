"""Future Action Impact Evaluator quantifying memory utility for downstream decisions.

[INPUT]
- toolkits.memory.action_impact.models::ActionImpactAssessment, ActionImpactCategory, ActionImpactTier (POS:
  Data models for Future Action Impact Filtering Gate.)

[OUTPUT]
- FutureActionImpactEvaluator: Evaluates whether an extracted fact will substantively alter future agent
  decisions.

[POS]
Future Action Impact Evaluator quantifying memory utility for downstream decisions.
"""

import re
from typing import ClassVar

from .models import (
    ActionImpactAssessment,
    ActionImpactCategory,
    ActionImpactTier,
)


class FutureActionImpactEvaluator:
    """Evaluates whether an extracted fact will substantively alter future agent decisions."""

    # Heuristic regex patterns for long-term directives and engineering decisions
    POLICY_PREFERENCE_PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"(必须|严禁|禁止|切勿|务必|始终|绝不|偏好|规范|原则|约定|只能使用)", re.IGNORECASE),
        re.compile(r"(always|never|must|prohibit|enforce|prefer|convention|standard)", re.IGNORECASE),
    )

    ENGINEERING_DECISION_PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"(采用|配置|运行在|部署于|数据库使用|端口|架构为|依赖版本|密钥保存在|接口定义)", re.IGNORECASE),
        re.compile(r"(deploy|database|architecture|version|endpoint|port|schema|credentials)", re.IGNORECASE),
    )

    EPHEMERAL_TASK_PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"(当前正在|暂时|稍后|第\d+步|已定位到|排查发现|测试中|临时)", re.IGNORECASE),
        re.compile(r"(currently|temporary|step\s*\d+|troubleshooting|inspecting|wip)", re.IGNORECASE),
    )

    CHITCHAT_SPECULATION_PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"(你好|早上好|晚安|累了|哈哈|随便|或许行|可能吧|先这样|无所谓)", re.IGNORECASE),
        re.compile(r"\b(hello|hi|good\s+morning|tired|maybe|guess|whatever|haha)\b", re.IGNORECASE),
    )

    def evaluate_fact(self, fact_text: str) -> ActionImpactAssessment:
        """Analyze a fact and score its likelihood of changing future decisions.

        Args:
            fact_text: Candidate fact extracted from dialogue.

        Returns:
            ActionImpactAssessment with quantified score and tier routing.
        """
        text = fact_text.strip()
        lower_text = text.lower()

        # 1. Core Preference or Policy Directive (Highest Authority)
        if any(p.search(lower_text) for p in self.POLICY_PREFERENCE_PATTERNS):
            score = 0.92
            category = ActionImpactCategory.CORE_PREFERENCE_OR_POLICY
            tier = ActionImpactTier.TIER_LONG_TERM_PERSIST
            rationale = "Explicit non-negotiable policy or behavioral preference that governs future actions."
            return ActionImpactAssessment(
                fact_text=text,
                category=category,
                impact_score=score,
                assigned_tier=tier,
                rationale=rationale,
                will_alter_future_actions=True,
            )

        # 2. Chitchat / Speculation check (Early intercept of noise)
        if any(p.search(lower_text) for p in self.CHITCHAT_SPECULATION_PATTERNS):
            score = 0.15
            category = ActionImpactCategory.CHITCHAT_OR_SPECULATION
            tier = ActionImpactTier.TIER_IMMEDIATE_DISCARD
            rationale = "Transient pleasantry or speculation with zero impact on future technical actions."
            return ActionImpactAssessment(
                fact_text=text,
                category=category,
                impact_score=score,
                assigned_tier=tier,
                rationale=rationale,
                will_alter_future_actions=False,
            )

        # 3. Ephemeral Task State or Transient Debugging Note (Preempts generic engineering terms)
        if any(p.search(lower_text) for p in self.EPHEMERAL_TASK_PATTERNS):
            score = 0.55
            category = ActionImpactCategory.EPHEMERAL_TASK_STATE
            tier = ActionImpactTier.TIER_SESSION_BUFFER
            rationale = "Transient task progress note; valuable during this session but obsolete once concluded."
            return ActionImpactAssessment(
                fact_text=text,
                category=category,
                impact_score=score,
                assigned_tier=tier,
                rationale=rationale,
                will_alter_future_actions=False,
            )

        # 4. Stable Engineering Fact or Architectural Decision
        if any(p.search(lower_text) for p in self.ENGINEERING_DECISION_PATTERNS):
            score = 0.85
            category = ActionImpactCategory.ENGINEERING_FACT_OR_DECISION
            tier = ActionImpactTier.TIER_LONG_TERM_PERSIST
            rationale = "Durable architectural choice or system configuration needed across sessions."
            return ActionImpactAssessment(
                fact_text=text,
                category=category,
                impact_score=score,
                assigned_tier=tier,
                rationale=rationale,
                will_alter_future_actions=True,
            )

        # 5. Default fallback based on information entropy (length and technical density)
        if len(text) > 30 and ("." in text or "=" in text or ":" in text or "/" in text):
            score = 0.80
            category = ActionImpactCategory.ENGINEERING_FACT_OR_DECISION
            tier = ActionImpactTier.TIER_LONG_TERM_PERSIST
            rationale = "Structured factual technical statement retained for cross-session continuity."
            will_alter = True
        elif len(text) > 15:
            score = 0.50
            category = ActionImpactCategory.EPHEMERAL_TASK_STATE
            tier = ActionImpactTier.TIER_SESSION_BUFFER
            rationale = "Uncategorized statement routed to ephemeral session buffer."
            will_alter = False
        else:
            score = 0.20
            category = ActionImpactCategory.CHITCHAT_OR_SPECULATION
            tier = ActionImpactTier.TIER_IMMEDIATE_DISCARD
            rationale = "Low-information terse fragment discarded as noise."
            will_alter = False

        return ActionImpactAssessment(
            fact_text=text,
            category=category,
            impact_score=score,
            assigned_tier=tier,
            rationale=rationale,
            will_alter_future_actions=will_alter,
        )
