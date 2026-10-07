"""Classifies incoming text into Fact, Procedural Rule, Dual-Track, or No-Signal.

[INPUT]
- toolkits.memory.dual_track_extraction.types::ExtractionTrackKind (POS: Typed data contracts for the dual
  track extraction subsystem.)

[OUTPUT]
- DualTrackSemanticClassifier: Classifies incoming text into Fact, Procedural Rule, Dual-Track, or
  No-Signal.

[POS]
Classifies incoming text into Fact, Procedural Rule, Dual-Track, or No-Signal.
"""

import logging
import re

from .types import ExtractionTrackKind

logger = logging.getLogger(__name__)

# Heuristic patterns indicating procedural / operational rules (When/If X, Do Y or Remember Z)
_PROCEDURAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(遇到|如果|当|一旦|若|只要).{0,50}?(记得|务必|必须|先|先查|先检查|要|统统|一律)", re.IGNORECASE),
    re.compile(r"(以后|之后|后续|日常).{0,50}?(写|做|用|跑|调用|提交).{0,50}?(记得|加上|带上|务必|必须)", re.IGNORECASE),
    re.compile(r"\b(when|if|whenever)\b.{0,80}?\b(always|never|make sure to|check first|remember to|guide to)\b", re.IGNORECASE),
    re.compile(r"(排障|报警|报错|故障).{0,50}?(先查|检查|看|核对)", re.IGNORECASE),
    re.compile(r"\b(rule|guideline|checklist|sop)\b", re.IGNORECASE),
]

# Heuristic patterns indicating declarative user facts or preferences
_FACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(名字叫|名字是|是一名|身份是|在做|坐标在|住址在|负责|运维)", re.IGNORECASE),
    re.compile(r"(喜欢|偏好|首选|习惯用|常用|主要用|擅长|核心技术栈是|语言是|数据库是|时区)", re.IGNORECASE),
    re.compile(r"\b(my name is|i prefer|i like|i work at|my stack is|our database is)\b", re.IGNORECASE),
    re.compile(r"(目标是|预算是|截止时间是|项目是)", re.IGNORECASE),
]


class DualTrackSemanticClassifier:
    """Classifies incoming text into Fact, Procedural Rule, Dual-Track, or No-Signal."""

    def classify(self, text: str) -> tuple[ExtractionTrackKind, float, str]:
        """Analyze text and determine the extraction track.

        Returns:
            Tuple of (ExtractionTrackKind, confidence, reason).
        """
        clean_text = text.strip()
        if len(clean_text) < 4:
            return ExtractionTrackKind.NO_SIGNAL, 1.0, "Input text too short to contain semantic facts or rules."

        is_procedural, proc_reason = self._detect_procedural(clean_text)
        is_fact, fact_reason = self._detect_fact(clean_text)

        if is_procedural and is_fact:
            return (
                ExtractionTrackKind.DUAL_TRACK,
                0.90,
                f"Dual track detected. Procedural: {proc_reason}; Fact: {fact_reason}",
            )

        if is_procedural:
            return (
                ExtractionTrackKind.PROCEDURAL_RULE,
                0.88,
                f"Procedural rule detected: {proc_reason}",
            )

        if is_fact:
            return (
                ExtractionTrackKind.FACT_PROFILE,
                0.85,
                f"Declarative fact detected: {fact_reason}",
            )

        return (
            ExtractionTrackKind.NO_SIGNAL,
            0.70,
            "No actionable operational rules (When/If ... Do) or user facts identified.",
        )

    def _detect_procedural(self, text: str) -> tuple[bool, str]:
        for pattern in _PROCEDURAL_PATTERNS:
            match = pattern.search(text)
            if match:
                return True, f"matched pattern '{match.group(0)}'"
        return False, ""

    def _detect_fact(self, text: str) -> tuple[bool, str]:
        for pattern in _FACT_PATTERNS:
            match = pattern.search(text)
            if match:
                return True, f"matched pattern '{match.group(0)}'"
        return False, ""
