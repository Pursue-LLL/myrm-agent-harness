"""[POS]: src/myrm_agent_harness/toolkits/memory/cognitive_box/intake_filter.py
[INPUT]: Raw candidate text, source session, and existing CognitiveMemoryEntry items.
[OUTPUT]: StrictMemoryIntakeFilter providing heuristic noise filtering, transient request discarding, and layer classification.
"""

import re

from myrm_agent_harness.toolkits.memory.cognitive_box.models import (
    CognitiveLayerKind,
    CognitiveMemoryEntry,
    IntakeDecisionKind,
    IntakeEvaluationReport,
)

_NOISE_PATTERNS = [
    r"^(?:hi|hello|hey|hola|greetings|你好|您好|哈喽|在吗|早安|晚安)(?:\s+(?:there|all|everyone|guys))?[!！.。\s]*$",
    r"^(?:ok|okay|sure|fine|yes|no|yeah|好的|收到|明白|行|好嘞|嗯嗯|哈哈|嘻嘻|感谢|谢谢|thanks|thx)(?:[,，、\s]+(?:ok|okay|sure|fine|yes|no|yeah|好的|收到|明白|行|好嘞|嗯嗯|哈哈|嘻嘻|感谢|谢谢|thanks|thx))*[!！.。\s]*$",
    r"^(?:test|testing|ping|pong|123|abc)[!！.。\s]*$",
]

_TRANSIENT_PATTERNS = [
    r"^(?:why|how|what|where|who|when|为什么|怎么|如何|帮我查|帮我找|看看这个).{0,30}\??$",
    r"^can you (?:help|check|explain|do).{0,30}\??$",
    r"^please (?:run|execute|check).{0,30}$",
]

_USER_PROFILE_KEYWORDS = {
    "偏好", "喜欢", "习惯", "倾向", "风格", "prefer", "preference",
    "favorite", "habit", "usually", "always use", "never use",
    "indent", "tabs", "spaces", "dark mode", "light mode",
}

_LESSONS_RULES_KEYWORDS = {
    "教训", "踩坑", "规则", "规范", "必须", "严禁", "禁止", "注意",
    "lesson", "rule", "guideline", "pitfall", "warning", "caution",
    "bug", "fix", "workaround", "requirement", "never do", "always do",
}


class StrictMemoryIntakeFilter:
    """Evaluates candidate memories against strict durable admission criteria."""

    @classmethod
    def evaluate(
        cls,
        raw_content: str,
        existing_entries: list[CognitiveMemoryEntry] | None = None,
        forced_layer: CognitiveLayerKind | None = None,
    ) -> IntakeEvaluationReport:
        """Screen raw text and decide whether to admit, drop as noise/transient, or update."""
        sanitized = raw_content.strip()

        # 1. Zero-length or trivial noise check
        if len(sanitized) < 3:
            return IntakeEvaluationReport(
                decision=IntakeDecisionKind.DROP_NOISE,
                layer=None,
                confidence=1.0,
                reason="Content length is too short to carry durable cognitive context.",
                sanitized_content=sanitized,
            )

        lowered = sanitized.lower()
        for pat in _NOISE_PATTERNS:
            if re.match(pat, lowered):
                return IntakeEvaluationReport(
                    decision=IntakeDecisionKind.DROP_NOISE,
                    layer=None,
                    confidence=0.95,
                    reason="Matched conversational salutation or chit-chat pattern.",
                    sanitized_content=sanitized,
                )

        # 2. Transient procedural query check
        for pat in _TRANSIENT_PATTERNS:
            if re.match(pat, lowered):
                return IntakeEvaluationReport(
                    decision=IntakeDecisionKind.DROP_TRANSIENT,
                    layer=None,
                    confidence=0.90,
                    reason="Matched transient one-off question or procedural command.",
                    sanitized_content=sanitized,
                )

        # 3. Layer classification & value scoring
        layer = forced_layer
        confidence = 0.85
        reason = "Passed durable intake admission screening."

        if layer is None:
            has_profile = any(kw in lowered for kw in _USER_PROFILE_KEYWORDS)
            has_lesson = any(kw in lowered for kw in _LESSONS_RULES_KEYWORDS)

            if has_profile and not has_lesson:
                layer = CognitiveLayerKind.USER_PROFILE
                reason = "Identified user profile or work preference cues."
            elif has_lesson:
                layer = CognitiveLayerKind.LESSONS_RULES
                reason = "Identified architectural rule, lesson learned, or constraint."
            else:
                # Default for generic statements with substance
                if len(sanitized) >= 20:
                    layer = CognitiveLayerKind.LESSONS_RULES
                    confidence = 0.75
                    reason = "Substantial cognitive statement admitted to lessons & rules layer."
                else:
                    return IntakeEvaluationReport(
                        decision=IntakeDecisionKind.DROP_TRANSIENT,
                        layer=None,
                        confidence=0.80,
                        reason="Short conversational fragment lacks clear durable value.",
                        sanitized_content=sanitized,
                    )

        # 4. Deduplication and update detection
        if existing_entries:
            for entry in existing_entries:
                if entry.layer == layer:
                    if entry.content.strip().lower() == lowered:
                        return IntakeEvaluationReport(
                            decision=IntakeDecisionKind.UPDATE_EXISTING,
                            layer=layer,
                            confidence=0.98,
                            reason="Exact duplicate of existing durable cognitive entry; updated timestamp.",
                            sanitized_content=sanitized,
                            existing_entry_id=entry.id,
                        )
                    # Simple sub-string or prefix overlap check
                    if (
                        len(sanitized) > 15
                        and (sanitized in entry.content or entry.content in sanitized)
                    ):
                        return IntakeEvaluationReport(
                            decision=IntakeDecisionKind.UPDATE_EXISTING,
                            layer=layer,
                            confidence=0.88,
                            reason="High semantic overlap with existing cognitive entry; refreshed.",
                            sanitized_content=sanitized,
                            existing_entry_id=entry.id,
                        )

        return IntakeEvaluationReport(
            decision=IntakeDecisionKind.ADMIT,
            layer=layer,
            confidence=confidence,
            reason=reason,
            sanitized_content=sanitized,
        )
