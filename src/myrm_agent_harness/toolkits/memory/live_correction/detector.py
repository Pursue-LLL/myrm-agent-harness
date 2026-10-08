"""Natural language correction detector extracting semantic slots from conversational utterances.

[INPUT]
- utterance: str (user raw input)

[OUTPUT]
- Optional[CorrectionSlot]: parsed slot or None if no correction detected

[POS]
myrm_agent_harness.toolkits.memory.live_correction.detector
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.live_correction.models import (
    CorrectionIntentKind,
    CorrectionSlot,
)

# Chinese regex patterns: (negated, corrected, subject, intent)
_ZH_PATTERNS: tuple[tuple[re.Pattern[str], CorrectionIntentKind], ...] = (
    # 我更喜欢/倾向于 Y 而不是 X
    (
        re.compile(
            r"(?:我|用户)?(?:更喜欢|倾向于|偏好|换成)\s*(?P<corrected>[^，,。.]+?)\s*(?:而不是|而非|不是)\s*(?P<negated>[^，,。.]+)",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.PREFERENCE_UPDATE,
    ),
    # 不喜欢/不要 X，(我)?喜欢/要 Y
    (
        re.compile(
            r"(?:我不喜欢|不要|别再|不再)\s*(?P<negated>[^，,。.]+?)\s*[，,]\s*(?:我)?(?:更喜欢|喜欢|只要|换成|要)\s*(?P<corrected>[^，,。.]+)",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.PREFERENCE_UPDATE,
    ),
    # [主体]? 不是/并非 X，而是/实际上是/其实是 Y
    (
        re.compile(
            r"(?:(?:你记错了|弄错了|你说的不对|不对)\s*[:：，,]?\s*)?(?:其实|实际上)?(?:(?P<subject>[^，,。.]+?)\s*)?(?:不是|并非)\s*(?P<negated>[^，,。.]+?)\s*[，,]?\s*(?:而是|实际上是|其实是|现在是|改成了)\s*(?P<corrected>[^，,。.]+)",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.FACT_SUPERSEDED,
    ),
    # 你记错了/弄错了，[主体]是 Y
    (
        re.compile(
            r"(?:你记错了|弄错了|你说的不对)\s*[:：，,]?\s*(?:其实|实际上)?(?P<corrected>[^，,。.]+)",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.FACT_SUPERSEDED,
    ),
    # 以后不要/禁止 X，要/请/严格遵守 Y
    (
        re.compile(
            r"(?:以后|后续|请)?(?:不要|别再|禁止|切勿)\s*(?P<negated>[^，,。.]+?)\s*[，,]?\s*(?:要|请|必须|严格遵守)\s*(?P<corrected>[^，,。.]+)",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.BEHAVIOR_RULE,
    ),
    # 撤回/忘记/删除关于 X 的记忆
    (
        re.compile(
            r"(?:撤回|忘记|删除|清除)(?:之前)?(?:关于)?\s*(?P<negated>[^，,。.]+?)\s*(?:的记忆|的设定|的记录)?$",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.RETRACT_MISTAKE,
    ),
)

# English regex patterns
_EN_PATTERNS: tuple[tuple[re.Pattern[str], CorrectionIntentKind], ...] = (
    # I prefer Y instead of / over / rather than X
    (
        re.compile(
            r"I\s+prefer\s+(?P<corrected>[^,.]+?)\s+(?:instead\s+of|over|rather\s+than)\s+(?P<negated>[^,.]+)",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.PREFERENCE_UPDATE,
    ),
    # Not X, but Y / Not X, actually Y
    (
        re.compile(
            r"(?:you're\s+wrong|not|incorrectly)\s*[:,]?\s*(?:it'?s\s+not\s+)?(?P<negated>[^,.]+?)\s*[,]?\s*(?:but|actually|it'?s\s+now)\s+(?P<corrected>[^,.]+)",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.FACT_SUPERSEDED,
    ),
    # Stop doing X, always/please do Y
    (
        re.compile(
            r"(?:stop|don'?t)\s+(?P<negated>[^,.]+?)\s*[,]?\s*(?:always|please|instead)\s+(?P<corrected>[^,.]+)",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.BEHAVIOR_RULE,
    ),
    # Forget / retract memory about X
    (
        re.compile(
            r"(?:forget|retract|delete|remove)\s+(?:about\s+)?(?P<negated>[^,.]+)$",
            re.IGNORECASE,
        ),
        CorrectionIntentKind.RETRACT_MISTAKE,
    ),
)


class NaturalLanguageCorrectionDetector:
    """Detects in-conversation live correction signals and parses key entities."""

    def detect(self, utterance: str) -> CorrectionSlot | None:
        """Scan input utterance for live correction intent and extract slot payload."""
        cleaned = utterance.strip()
        if not cleaned or len(cleaned) > 1000:
            return None

        # Check Chinese patterns
        for pattern, intent in _ZH_PATTERNS:
            match = pattern.search(cleaned)
            if match:
                groups = match.groupdict()
                negated = groups.get("negated", "").strip() if groups.get("negated") else None
                corrected = groups.get("corrected", "").strip() if groups.get("corrected") else ""
                subject = groups.get("subject", "").strip() if groups.get("subject") else None

                # Clean composite negated strings like "主数据库不是 Postgres"
                if negated and ("不是" in negated or "并非" in negated):
                    parts = re.split(r"(?:不是|并非)\s*", negated, maxsplit=1)
                    if len(parts) == 2:
                        if not subject:
                            subject = parts[0].strip() or None
                        negated = parts[1].strip() or None

                if not corrected and intent == CorrectionIntentKind.RETRACT_MISTAKE and negated:
                    corrected = f"撤回: {negated}"

                if corrected or negated:
                    return CorrectionSlot(
                        corrected_value=corrected or (negated or ""),
                        negated_value=negated,
                        subject=subject,
                        intent=intent,
                        confidence=0.95,
                        raw_utterance=cleaned,
                    )

        # Check English patterns
        for pattern, intent in _EN_PATTERNS:
            match = pattern.search(cleaned)
            if match:
                groups = match.groupdict()
                negated = groups.get("negated", "").strip() if groups.get("negated") else None
                corrected = groups.get("corrected", "").strip() if groups.get("corrected") else ""
                subject = groups.get("subject", "").strip() if groups.get("subject") else None
                if not corrected and intent == CorrectionIntentKind.RETRACT_MISTAKE and negated:
                    corrected = f"retract: {negated}"

                if corrected or negated:
                    return CorrectionSlot(
                        corrected_value=corrected or (negated or ""),
                        negated_value=negated,
                        subject=subject,
                        intent=intent,
                        confidence=0.95,
                        raw_utterance=cleaned,
                    )

        return None
