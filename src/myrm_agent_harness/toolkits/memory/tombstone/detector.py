"""[POS]: src/myrm_agent_harness/toolkits/memory/tombstone/detector.py
[INPUT]: Collections of TombstoneCandidateItem memory directives.
[OUTPUT]: Identified ContradictionPair instances with confidence scores and temporal adjudication.
"""

import re

from myrm_agent_harness.toolkits.memory.tombstone.models import (
    ContradictionPair,
    TombstoneCandidateItem,
)

# Canonical opposing topic pairs and mutual exclusions
_ANTITHETICAL_TOPIC_RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    # (topic_label, positive_group, opposing_group)
    (
        "language_preference",
        ("中文", "汉语", "chinese", "用中文回复", "使用中文"),
        ("英文", "英语", "english", "reply in english", "use english only"),
    ),
    (
        "test_framework",
        ("pytest", "使用pytest", "prefer pytest"),
        ("unittest", "使用unittest", "prefer unittest"),
    ),
    (
        "code_comments",
        ("详尽注释", "详细注释", "写注释", "添加注释", "注释与docstring", "always document"),
        ("不要注释", "不写注释", "极简代码无注释", "不要写任何注释", "不添加注释", "omit comments", "no comments"),
    ),
    (
        "typing_discipline",
        ("strict typing", "严格类型", "禁止any", "强类型"),
        ("dynamic typing", "弱类型", "不用类型注解", "no type hints"),
    ),
    (
        "theme_mode",
        ("dark mode", "深色模式", "暗色主题"),
        ("light mode", "浅色模式", "明亮主题"),
    ),
    (
        "frontend_stack",
        ("react", "优先使用react"),
        ("vue", "优先使用vue"),
    ),
]

_POLARITY_PATTERNS: list[tuple[str, str]] = [
    (r"(?:必须|务必|优先|强烈推荐|一律(?:使用)?)(?:\s*(?:使用|采用|配置|引入))?\s*([a-zA-Z0-9_]+|[a-zA-Z0-9_\u4e00-\u9fa5]{2,})", "prefer"),
    (r"(?:严禁|禁止|不要|杜绝|切勿(?:使用)?)(?:\s*(?:使用|采用|配置|引入))?\s*([a-zA-Z0-9_]+|[a-zA-Z0-9_\u4e00-\u9fa5]{2,})", "prohibit"),
    (r"always\s+(?:use|prefer)\s+([a-zA-Z0-9_]+)", "prefer"),
    (r"never\s+(?:use|avoid)\s+([a-zA-Z0-9_]+)", "prohibit"),
]


class PreferenceContradictionDetector:
    """Scans memory entries for mutual exclusions, negative polarity reversals, and outdated directives."""

    def detect_contradictions(
        self, memories: list[TombstoneCandidateItem]
    ) -> list[ContradictionPair]:
        """Examine memory items pairwise and yield contradictions with temporal adjudication."""
        contradictions: list[ContradictionPair] = []
        n = len(memories)

        for i in range(n):
            for j in range(i + 1, n):
                item_a = memories[i]
                item_b = memories[j]

                pair = self._check_pair_contradiction(item_a, item_b)
                if pair:
                    contradictions.append(pair)

        return contradictions

    def _check_pair_contradiction(
        self, a: TombstoneCandidateItem, b: TombstoneCandidateItem
    ) -> ContradictionPair | None:
        """Evaluate if two memory items express contradictory propositions."""
        # 1. Check against predefined domain antithetical topic matrices
        text_a_lower = a.content.lower()
        text_b_lower = b.content.lower()

        for topic, group_pos, group_opp in _ANTITHETICAL_TOPIC_RULES:
            has_pos_a = any(k in text_a_lower for k in group_pos)
            has_opp_a = any(k in text_a_lower for k in group_opp)
            has_pos_b = any(k in text_b_lower for k in group_pos)
            has_opp_b = any(k in text_b_lower for k in group_opp)

            if (has_pos_a and has_opp_b) or (has_opp_a and has_pos_b):
                return self._build_pair(
                    a,
                    b,
                    topic=topic,
                    confidence=0.95,
                    reason=f"Opposing preferences detected within domain '{topic}'",
                )

        # 2. Check polarity contradictions (prefer X vs prohibit X)
        polarity_a = self._extract_polarities(a.content)
        polarity_b = self._extract_polarities(b.content)

        for target_a, pol_a in polarity_a.items():
            if target_a in polarity_b:
                pol_b = polarity_b[target_a]
                if (pol_a == "prefer" and pol_b == "prohibit") or (
                    pol_a == "prohibit" and pol_b == "prefer"
                ):
                    return self._build_pair(
                        a,
                        b,
                        topic=target_a,
                        confidence=0.90,
                        reason=f"Direct polarity conflict on target entity '{target_a}' ({pol_a} vs {pol_b})",
                    )

        return None

    def _extract_polarities(self, text: str) -> dict[str, str]:
        """Extract entities and associated positive/negative preference polarities."""
        polarities: dict[str, str] = {}
        for pattern, pol_type in _POLARITY_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for m in matches:
                target = m.group(1).lower().strip()
                if len(target) >= 2:
                    polarities[target] = pol_type
        return polarities

    def _build_pair(
        self,
        a: TombstoneCandidateItem,
        b: TombstoneCandidateItem,
        topic: str,
        confidence: float,
        reason: str,
    ) -> ContradictionPair:
        """Designate newer memory as superseding and older memory as outdated candidate."""
        if a.created_at >= b.created_at:
            new_item, old_item = a, b
        else:
            new_item, old_item = b, a

        return ContradictionPair(
            new_memory_id=new_item.memory_id,
            outdated_memory_id=old_item.memory_id,
            topic_keyword=topic,
            confidence_score=confidence,
            reason=reason,
        )
