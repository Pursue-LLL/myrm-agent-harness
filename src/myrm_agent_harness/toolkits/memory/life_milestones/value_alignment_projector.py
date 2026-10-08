"""Value System Alignment Projector weaving lifelong philosophical evolution into context.

Topic 01 Item 137: ValueSystemAlignmentProjector.
Ensures the Agent understands the user's worldview evolution across decades,
preventing superficial or conflicting advice during deep life decisions.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.life_milestones.models import (
    ContextProjectionBundle,
    PrivacyIntimacyLevel,
    ValueSystemNode,
)
from myrm_agent_harness.toolkits.memory.life_milestones.timeline_engine import (
    LifeMilestonesEngine,
)


class ValueSystemAlignmentProjector:
    """Projects user value system evolution and relevant life milestones into conversational context."""

    _INTENT_TRIGGER_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(职业|跳槽|辞职|创业|转行|方向|迷茫|选择|抉择)", re.IGNORECASE),
        re.compile(r"(家庭|结婚|孩子|父母|亲情|陪伴|爱人|伴侣)", re.IGNORECASE),
        re.compile(r"(城市|搬家|买房|定居|离开|故乡|归宿)", re.IGNORECASE),
        re.compile(r"(价值观|意义|人生活法|追求|内耗|焦虑|初心|哲学)", re.IGNORECASE),
        re.compile(r"(健康|身体|衰老|疾病|平衡|作息|身心)", re.IGNORECASE),
    )

    def __init__(self, timeline_engine: LifeMilestonesEngine) -> None:
        self._timeline = timeline_engine
        self._values: dict[str, ValueSystemNode] = {}

    def register_value(self, node: ValueSystemNode) -> None:
        """Register or update a value system belief node."""
        self._values[node.value_id] = node

    def evolve_value(
        self,
        new_node: ValueSystemNode,
        prior_node_id: str | None = None,
    ) -> None:
        """Evolve a value belief, archiving the prior stance and establishing a causal link."""
        if prior_node_id and prior_node_id in self._values:
            old = self._values[prior_node_id]
            # Replace old with inactive version
            self._values[prior_node_id] = ValueSystemNode(
                value_id=old.value_id,
                theme=old.theme,
                current_stance=old.current_stance,
                prior_belief=old.prior_belief,
                transition_catalyst=old.transition_catalyst,
                trigger_milestone_ids=old.trigger_milestone_ids,
                effective_since_year=old.effective_since_year,
                is_active=False,
                weight=old.weight * 0.5,
            )

        self._values[new_node.value_id] = new_node

    def get_active_values(self) -> list[ValueSystemNode]:
        """Fetch all currently active value system beliefs."""
        active = [v for v in self._values.values() if v.is_active]
        active.sort(key=lambda v: v.weight, reverse=True)
        return active

    def detect_deep_life_intent(self, query_text: str) -> bool:
        """Detect whether user query involves philosophical, emotional, or major life choices."""
        query_stripped = query_text.strip()
        return any(p.search(query_stripped) for p in self._INTENT_TRIGGER_PATTERNS)

    def project_context(
        self,
        query_text: str,
        max_intimacy: PrivacyIntimacyLevel = PrivacyIntimacyLevel.INTIMATE_PERSONAL,
        force_projection: bool = False,
    ) -> ContextProjectionBundle:
        """Produce an empathetic, grounded context projection for agent prompting."""
        should_project = force_projection or self.detect_deep_life_intent(query_text)
        if not should_project:
            return ContextProjectionBundle(
                projected_text="",
                relevant_milestone_count=0,
                active_values=[],
                applied_intimacy_level=max_intimacy,
            )

        active_values = self.get_active_values()
        relevant_milestones = self._timeline.list_milestones(
            max_intimacy=max_intimacy,
        )

        # Assemble compact empathetic prompt
        lines: list[str] = [
            "### 【用户生命历程与核心价值观坐标】",
            "> 提醒：用户并非一张空白的纸。请结合用户如下心路历程与核心价值观，以温情、沉稳且具有历史深度的视角交流：",
        ]

        # 1. Active values with causal background
        if active_values:
            lines.append("- **主导价值观与人生信条**:")
            for val in active_values[:4]:
                if val.prior_belief and val.transition_catalyst:
                    lines.append(
                        f"  - [{val.theme}] 当前主张：{val.current_stance}（注：由早期‘{val.prior_belief}’经‘{val.transition_catalyst}’蜕变而来）"
                    )
                else:
                    lines.append(f"  - [{val.theme}] {val.current_stance}")

        # 2. Key life milestones
        turning_points = [m for m in relevant_milestones if m.significance_score >= 0.80]
        recent_or_crucial = turning_points[-5:] if turning_points else relevant_milestones[-3:]
        if recent_or_crucial:
            lines.append("- **人生关键地标与拐点**:")
            for ms in recent_or_crucial:
                lines.append(f"  - {ms.year}年 ({ms.category.value}): {ms.title} — {ms.long_term_impact}")

        lines.append(
            "- **回复原则**: 保持共情与敬畏，尊重其人生抉择的连续性，严禁以傲慢、冰冷的外包工具语气进行说教。"
        )

        projected_str = "\n".join(lines)
        return ContextProjectionBundle(
            projected_text=projected_str,
            relevant_milestone_count=len(recent_or_crucial),
            active_values=[v.current_stance for v in active_values],
            applied_intimacy_level=max_intimacy,
        )
