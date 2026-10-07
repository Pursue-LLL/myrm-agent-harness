"""Deterministic Task Detector identifying mechanical, non-reasoning prompts.

Detects repetitive, translation, formatting, or trivial code hygiene tasks
to recommend zero-thinking budget direct routing, eliminating expensive reasoning decoding.
"""

from __future__ import annotations

import re

from .zero_thinking_types import (
    DeterministicTaskDetection,
    ThinkingBudgetMode,
)


class DeterministicTaskDetector:
    """Heuristic detector determining if a prompt is mechanical and warrants zero thinking budget."""

    _PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
        # 1. Formatting and Schema Conversion
        (
            "format_conversion",
            re.compile(
                r"\b(?:convert\s+(?:\w+\s+)*to\s+(?:json|markdown|csv|table)|format\s+(?:\w+\s+)*as\s+(?:json|markdown|table)|parse\s+csv|格式化|转为json|转成json)\b",
                re.IGNORECASE,
            ),
            0.95,
        ),
        # 2. Translation
        (
            "translation",
            re.compile(
                r"\b(?:translate\s+(?:\w+\s+)*(?:to|into)\s+[a-z]+|翻译成|翻译为|英译中|中译英)\b",
                re.IGNORECASE,
            ),
            0.92,
        ),
        # 3. Simple text hygiene / Sorting / Deduplication
        (
            "text_hygiene",
            re.compile(
                r"\b(?:sort\s+alphabetically|deduplicate|remove\s+duplicates|去重|按字母排序)\b",
                re.IGNORECASE,
            ),
            0.90,
        ),
        # 4. Explicit user fast-lane request
        (
            "explicit_fast_path",
            re.compile(
                r"\b(?:skip\s+thinking|fast\s+output|极速直出|跳过推理|no\s+reasoning|zero\s+thinking)\b",
                re.IGNORECASE,
            ),
            1.0,
        ),
        # 5. Trivial Renaming or Typo fixes
        (
            "trivial_renaming",
            re.compile(
                r"\b(?:rename\s+variable\s+\w+\s+to\s+\w+|fix\s+typo\s+in|修改变量名|修正错别字)\b",
                re.IGNORECASE,
            ),
            0.88,
        ),
    ]

    def detect(self, prompt: str) -> DeterministicTaskDetection:
        """Analyze prompt semantics and determine if zero thinking budget should be applied."""
        clean_prompt = prompt.strip()
        if not clean_prompt:
            return DeterministicTaskDetection(
                is_deterministic=False,
                confidence=0.0,
                suggested_mode=ThinkingBudgetMode.AUTO,
                reason="Empty prompt.",
            )

        # Check against high-confidence patterns
        for pattern_name, regex, confidence in self._PATTERNS:
            match = regex.search(clean_prompt)
            if match:
                return DeterministicTaskDetection(
                    is_deterministic=True,
                    confidence=confidence,
                    detected_pattern=pattern_name,
                    suggested_mode=ThinkingBudgetMode.ZERO_DIRECT,
                    reason=f"Detected deterministic pattern '{pattern_name}' (matched: '{match.group(0)}').",
                )

        return DeterministicTaskDetection(
            is_deterministic=False,
            confidence=0.0,
            detected_pattern=None,
            suggested_mode=ThinkingBudgetMode.AUTO,
            reason="Prompt requires normal contextual reasoning or complex architectural planning.",
        )
