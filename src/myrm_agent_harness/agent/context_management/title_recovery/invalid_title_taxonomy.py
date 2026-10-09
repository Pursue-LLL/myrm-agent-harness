"""Taxonomy classifier detecting structural defects and hallucinations in LLM titles.

[INPUT]
- title_recovery_types: InvalidTitleReason, TitleRecoveryConfig, TitleValidationResult.

[OUTPUT]
- InvalidTitleTaxonomy: Classifies and cleanses raw LLM generated titles.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.title_recovery
- Module: invalid_title_taxonomy.py
"""

import re
from typing import List, Tuple

from myrm_agent_harness.agent.context_management.title_recovery.title_recovery_types import (
    InvalidTitleReason,
    TitleRecoveryConfig,
    TitleValidationResult,
)


class InvalidTitleTaxonomy:
    """Classifies structural failure modes in model-emitted conversation titles."""

    _COT_PATTERNS = (
        re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE),
        re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE),
        re.compile(r"<thought>.*?</thought>", re.DOTALL | re.IGNORECASE),
        re.compile(r"^\s*Thinking Process:\s*", re.IGNORECASE),
        re.compile(r"^\s*Thought:\s*", re.IGNORECASE),
    )

    _MENU_PATTERNS = (
        re.compile(r"(?:^|\n)\s*(?:Option\s*\d+|Choice\s*\d+|方案\s*\d+)[:：]", re.IGNORECASE),
        re.compile(r"(?:^|\n)\s*(?:1[.)、]|一[、.])[^\n]+\n\s*(?:2[.)、]|二[、.])", re.MULTILINE),
        re.compile(r"(?:Here are|Here's a few|以下是几个|可选标题)", re.IGNORECASE),
    )

    _PROSE_PATTERNS = (
        re.compile(r"^(?:Here is a title|Sure, here's a title|Certainly! Here's|Sure!|Certainly!|Okay, here is)[:：\s]*", re.IGNORECASE),
        re.compile(r"^(?:I suggest|I would suggest|How about|My suggestion is)[:：\s]*", re.IGNORECASE),
        re.compile(r"^(?:我建议的标题|生成的标题如下|为你生成的标题)[:：\s]*", re.IGNORECASE),
    )

    def __init__(self, config: TitleRecoveryConfig) -> None:
        self._config = config

    def validate_and_cleanse(self, raw_title: str) -> TitleValidationResult:
        """Inspects, classifies, and strips superficial wrappers from candidate title.

        Args:
            raw_title: Raw string returned by title generation LLM.

        Returns:
            TitleValidationResult indicating cleanliness and validity.
        """
        if not raw_title or not raw_title.strip():
            return TitleValidationResult(
                is_valid=False,
                cleaned_title="",
                reasons=(InvalidTitleReason.EMPTY_OR_WHITESPACE,),
                diagnostic_details="Candidate title is empty or pure whitespace",
            )

        reasons: List[InvalidTitleReason] = []
        text = raw_title.strip()

        # 1. CoT / Thinking tag leak
        for pattern in self._COT_PATTERNS:
            if pattern.search(text):
                reasons.append(InvalidTitleReason.COT_LEAK)
                break

        # 2. Option menu format
        for pattern in self._MENU_PATTERNS:
            if pattern.search(text):
                reasons.append(InvalidTitleReason.OPTION_MENU)
                break

        # 3. Code block wrap
        if "```" in text:
            reasons.append(InvalidTitleReason.CODE_BLOCK_WRAP)

        # Cleanse superficial wraps (quotes, common prefix tags, conversational lead-ins)
        cleaned = text
        for pattern in self._PROSE_PATTERNS:
            cleaned = pattern.sub("", cleaned).strip()

        cleaned = re.sub(
            r"^(?:title|标题|chat title|conversation title|topic)[:：\s]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()

        for prefix in self._config.strip_title_prefixes:
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip()

        cleaned = cleaned.strip("\"'“”‘’「」『』【】《》（）()[]{}。，,:： \t\n")

        # 4. First person conversational prose check on residual/unstripable text
        residual_prose_match = re.search(
            r"(?:\b(?:i think|i would|i suggest|let's|let us|we can|we should|my proposal|for you)\b|我觉得|我认为|我们来|推荐你)",
            cleaned,
            re.IGNORECASE,
        )
        if residual_prose_match:
            reasons.append(InvalidTitleReason.FIRST_PERSON_PROSE)
        elif len(cleaned) < self._config.min_length and any(p.search(text) for p in self._PROSE_PATTERNS):
            reasons.append(InvalidTitleReason.FIRST_PERSON_PROSE)

        # 5. Length checks on cleaned candidate
        if len(cleaned) < self._config.min_length or len(cleaned) > self._config.max_length:
            reasons.append(InvalidTitleReason.LENGTH_OUT_OF_BOUNDS)

        # 6. Garbage punctuation check (contains no alphanumeric or CJK ideographs)
        if cleaned and not re.search(r"[a-zA-Z0-9\u4e00-\u9fff]", cleaned):
            reasons.append(InvalidTitleReason.PUNCTUATION_OR_GARBAGE)

        is_valid = len(reasons) == 0 and len(cleaned) >= self._config.min_length

        diagnostics = (
            "Title is valid and clean"
            if is_valid
            else f"Rejected due to: {', '.join(r.value for r in reasons)}"
        )

        return TitleValidationResult(
            is_valid=is_valid,
            cleaned_title=cleaned if is_valid else "",
            reasons=tuple(reasons) if reasons else (InvalidTitleReason.VALID,),
            diagnostic_details=diagnostics,
        )
