"""Descriptive-only fact grammar validator and imperative instruction rewriter.

[INPUT]
- re: Pattern matching for imperative structures
- myrm_agent_harness.toolkits.memory.screen_observation.types: DescriptiveFactCandidate

[OUTPUT]
- DescriptiveFactValidator: Enforces descriptive grammar ('The user did X' vs 'Do X')

[POS]
Harness framework layer implementation of ChatGPT Desktop Skysight-style
syntax validator ensuring extracted memory statements are strictly descriptive facts.
Strict typing applied: No `any` types allowed.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.screen_observation.types import (
    DescriptiveFactCandidate,
)

# Common imperative verb prefixes in English
IMPERATIVE_EN_PREFIXES = (
    "do",
    "run",
    "execute",
    "configure",
    "install",
    "delete",
    "remove",
    "send",
    "format",
    "set",
    "change",
    "update",
    "modify",
    "always",
    "never",
    "make sure to",
)

# Common imperative verb prefixes in Chinese
IMPERATIVE_CN_PREFIXES = (
    "请",
    "必须",
    "务必",
    "切记",
    "执行",
    "运行",
    "配置",
    "安装",
    "删除",
    "重置",
    "千万不要",
    "强制",
)

# Third-person descriptive subject prefixes indicating compliant descriptive facts
DESCRIPTIVE_SUBJECT_PREFIXES = (
    "the user",
    "user",
    "the developer",
    "the agent",
    "用户",
    "开发者",
    "系统观察到",
    "在会话中",
    "当处理",
)


class DescriptiveFactValidator:
    """Enforces that candidate facts extracted from screen observations adhere strictly

    to third-person descriptive syntax rather than imperative command syntax.
    """

    def __init__(self) -> None:
        self._imperative_pattern_en = re.compile(
            r"^(?:" + "|".join(IMPERATIVE_EN_PREFIXES) + r")\b",
            re.IGNORECASE,
        )
        self._imperative_pattern_cn = re.compile(
            r"^(?:" + "|".join(IMPERATIVE_CN_PREFIXES) + r")",
        )

    def validate(self, statement: str) -> DescriptiveFactCandidate:
        """Evaluate a statement for descriptive grammar compliance and provide rewritten alternative if needed."""
        trimmed = statement.strip()
        violations: list[str] = []
        is_imperative = False

        if not trimmed:
            return DescriptiveFactCandidate(
                statement=statement,
                is_descriptive=False,
                imperative_detected=True,
                violation_reasons=["Empty statement"],
                rewritten_statement="",
            )

        lower_trimmed = trimmed.lower()

        # Check if statement starts with an imperative command verb
        if self._imperative_pattern_en.match(lower_trimmed):
            is_imperative = True
            violations.append("Statement begins with an English imperative verb without a descriptive subject")
        elif self._imperative_pattern_cn.match(trimmed):
            is_imperative = True
            violations.append("Statement begins with a Chinese imperative verb without a descriptive subject")

        # Check if statement lacks third-person descriptive subject
        has_descriptive_subject = any(lower_trimmed.startswith(prefix) for prefix in DESCRIPTIVE_SUBJECT_PREFIXES)

        if not has_descriptive_subject and is_imperative:
            violations.append("Missing explicit third-person descriptive anchor (e.g. 'The user did ...' / '用户...')")

        # Determine if statement is acceptable
        is_descriptive = len(violations) == 0 and (has_descriptive_subject or not is_imperative)

        # Generate rewritten statement if imperative was detected
        rewritten = trimmed
        if is_imperative or not is_descriptive:
            rewritten = self._rewrite_to_descriptive(trimmed)

        return DescriptiveFactCandidate(
            statement=trimmed,
            is_descriptive=is_descriptive,
            imperative_detected=is_imperative,
            violation_reasons=violations,
            rewritten_statement=rewritten,
        )

    def _rewrite_to_descriptive(self, text: str) -> str:
        """Normalize an imperative statement into an objective third-person descriptive fact."""
        cleaned = text.strip()

        # Remove leading imperative keywords if present
        for p in IMPERATIVE_CN_PREFIXES:
            if cleaned.startswith(p):
                cleaned = cleaned[len(p) :].strip()
                break

        for p in IMPERATIVE_EN_PREFIXES:
            if cleaned.lower().startswith(p):
                cleaned = cleaned[len(p) :].strip()
                break

        # Check if language appears to be predominantly Chinese
        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", text))

        if has_chinese:
            return f"用户在操作中执行并观察了: {cleaned}"
        return f"The user was observed performing: {cleaned}"
