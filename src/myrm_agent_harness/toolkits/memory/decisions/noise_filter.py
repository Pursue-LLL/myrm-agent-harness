"""[POS]: src/myrm_agent_harness/toolkits/memory/decisions/noise_filter.py
[INPUT]: Raw textual inputs from user messages or model transcripts.
[OUTPUT]: Boolean noise discrimination and sanitized text stripped of harness system prompts.
"""

import re

# System reminder and instructions injection patterns from harness runtime
_SYSTEM_NOISE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*<system-reminder>", re.IGNORECASE),
    re.compile(r"^\s*<context-boundary>", re.IGNORECASE),
    re.compile(r"^\s*<user_rules>", re.IGNORECASE),
    re.compile(r"^\s*<RULE\[", re.IGNORECASE),
    re.compile(r"^\s*Updated instructions from", re.IGNORECASE),
    re.compile(r"^\s*Instructions from", re.IGNORECASE),
    re.compile(r"^\s*AGENTS\.md", re.IGNORECASE),
)

_TECHNICAL_DECISION_CUES: tuple[str, ...] = (
    "采用", "选择", "使用", "废弃", "取代", "重构为", "架构", "设计为",
    "use", "adopt", "choose", "supersede", "replace", "switch to",
    "architecture", "decision", "selected", "refactored to",
)


class IngestionNoiseFilter:
    """Discriminates and strips harness-level system noise and paste bloat."""

    @classmethod
    def is_noise(cls, text: str) -> bool:
        """Return True if the text represents system instruction noise rather than genuine decisions."""
        stripped = text.strip()
        if len(stripped) < 5:
            return True

        for pattern in _SYSTEM_NOISE_PATTERNS:
            if pattern.search(stripped):
                return True

        # Pure Markdown frontmatter or fenced system metadata check
        return bool(
            stripped.startswith("---")
            and stripped.count("---") >= 2
            and len(stripped.splitlines()) < 10
            and any(cue in stripped.lower() for cue in ("system_role", "system_prompt", "agent_rules"))
        )

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Strip surrounding XML-like meta wrappers and normalize whitespace."""
        cleaned = text.strip()
        cleaned = re.sub(r"^```[a-zA-Z]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
        return cleaned.strip()

    @classmethod
    def contains_decision_cue(cls, text: str) -> bool:
        """Check whether the content carries explicit technical decision intent."""
        lower = text.lower()
        return any(cue in lower for cue in _TECHNICAL_DECISION_CUES)
