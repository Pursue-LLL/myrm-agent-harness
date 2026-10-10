"""
[INPUT]
- Spoken transcript string from speech-to-text
- VoiceVisualConfig with confidence threshold and custom trigger rules

[OUTPUT]
- VisualIntentDecision: has_visual_intent, category, confidence, matched_triggers, clean_text

[POS]
Sub-millisecond heuristic intent detector for visual screen context queries (Item 303).
Analyzes linguistic cues and deictic references to decide whether an automated screenshot
must be captured and attached before dispatching to the LLM.
"""

import re
from typing import ClassVar

from .voice_visual_types import (
    VisualIntentCategory,
    VisualIntentDecision,
    VoiceVisualConfig,
)


class VoiceVisualIntentDetector:
    """Fast rule-based detector for screen visual references in spoken user utterances."""

    _CLEAN_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^[，。！？\s]*(?:请(?:帮我|给我)?|麻烦你?(?:帮我)?|帮我|给我|现在|看一下|看下|查一下)\s*",
        re.IGNORECASE,
    )

    # Categories with associated compiled regex patterns and baseline confidence
    _CATEGORY_RULES: ClassVar[list[tuple[VisualIntentCategory, re.Pattern[str], float]]] = [
        (
            VisualIntentCategory.ERROR_DIAGNOSIS,
            re.compile(
                r"(?:这(?:个|段)?(?:报错|异常|错误|error|exception|crash|stacktrace)|"
                r"为什么(?:报错|报红|挂了|挂掉)|"
                r"why (?:is|does) this (?:error|exception|fail|crash)|"
                r"fix this error|solve this error)",
                re.IGNORECASE,
            ),
            0.95,
        ),
        (
            VisualIntentCategory.UI_ELEMENT_QUERY,
            re.compile(
                r"(?:这(?:个|条)?(?:按钮|图标|菜单|弹窗|输入框|下拉框|组件|卡片|视图|tab|button|icon|modal|dialog)|"
                r"点(?:这(?:个|里)|它)?没反应|"
                r"左(?:上|下)?角|右(?:上|下)?角|"
                r"what is this button|click this|this modal|this icon)",
                re.IGNORECASE,
            ),
            0.90,
        ),
        (
            VisualIntentCategory.CODE_INSPECTION,
            re.compile(
                r"(?:这(?:段|行|个)?(?:代码|函数|类|方法|脚本|code|function|snippet)|"
                r"终端(?:里|输出|日志)?(?:写的是啥|什么意思)|"
                r"review this code|look at this function|check this snippet)",
                re.IGNORECASE,
            ),
            0.88,
        ),
        (
            VisualIntentCategory.GENERAL_SCREEN,
            re.compile(
                r"(?:(?:当前|这个)?屏幕(?:上|里)?(?:(?:显示|写|是|有)?(?:的是)?(?:什么|啥|内容)|[^\w\s]*$)|"
                r"看(?:一下|下)?(?:这里|这个|屏幕)|"
                r"这(?:里|个)怎么(?:弄|写|填|搞|处理)|"
                r"look at (?:my|this)?\s*screen|what is (?:this|here|on (?:my|the) screen)|on my screen)",
                re.IGNORECASE,
            ),
            0.80,
        ),
    ]

    def __init__(self, config: VoiceVisualConfig | None = None) -> None:
        self._config = config or VoiceVisualConfig()

    def detect(self, transcript: str) -> VisualIntentDecision:
        """Evaluate if the user's spoken utterance requires screenshot context."""
        if not self._config.enabled or not transcript.strip():
            return VisualIntentDecision(
                has_visual_intent=False,
                category=VisualIntentCategory.NO_VISUAL_INTENT,
                confidence=0.0,
                matched_triggers=[],
                clean_text=transcript.strip(),
            )

        clean_text = transcript.strip()
        prev = ""
        while clean_text != prev:
            prev = clean_text
            clean_text = self._CLEAN_RE.sub("", clean_text).strip()

        # Check custom triggers first if configured
        matched_triggers: list[str] = []
        for trigger in self._config.custom_triggers:
            if trigger.lower() in clean_text.lower():
                matched_triggers.append(trigger)

        if matched_triggers:
            return VisualIntentDecision(
                has_visual_intent=True,
                category=VisualIntentCategory.GENERAL_SCREEN,
                confidence=1.0,
                matched_triggers=matched_triggers,
                clean_text=clean_text,
            )

        # Match category rules in priority order
        for category, pattern, confidence in self._CATEGORY_RULES:
            matches = pattern.findall(clean_text)
            if matches:
                # Flat trigger list
                triggers = [m if isinstance(m, str) else m[0] for m in matches if m]
                if confidence >= self._config.min_confidence_threshold:
                    return VisualIntentDecision(
                        has_visual_intent=True,
                        category=category,
                        confidence=confidence,
                        matched_triggers=triggers,
                        clean_text=clean_text,
                    )

        return VisualIntentDecision(
            has_visual_intent=False,
            category=VisualIntentCategory.NO_VISUAL_INTENT,
            confidence=0.0,
            matched_triggers=[],
            clean_text=clean_text,
        )
