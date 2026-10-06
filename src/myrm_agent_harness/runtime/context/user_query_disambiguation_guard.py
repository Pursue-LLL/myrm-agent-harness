"""User Query Disambiguation Guard & Compaction Prompt Preservation (Pi Harness v2 Item 29).

Implements bulletproof user query disambiguation and custom compaction prompt preservation:
1. User Query & Tool Search Disambiguation:
   Prevents upstream clients prepending `<current_datetime>...</current_datetime>` or environment tags
   from accidentally misclassifying human queries as grep/search results and deleting user instructions.
2. Two-Line Absolute Floor & Path-Like Verification:
   Search result detectors strictly enforce:
   - Path-like pre-colon segments (strictly rejecting XML/HTML tags and key=value pairs like `<...>`, `key=val`).
   - A minimum two-matching-line floor, preventing single-line accidental matches from wiping out prompts.
   - Human turn immunity: Human/User turns are never routed to destructive search folding.
3. Custom Compaction Prompt Fallback Preservation:
   Guarantees that when automatic full-summarization fallback is triggered under token pressure,
   user-configured custom summary prompts are 100% preserved instead of silently regressing to default templates.

[INPUT]
- content: str
- is_human_turn: bool
- contract: CompactionPromptFallbackContract

[OUTPUT]
- ContentCategory
- MetadataPrefixKind
- ParsedUserQuery
- CompactionPromptFallbackContract
- UserQueryDisambiguationGuard

[POS]
Harness runtime context layer. Protects user prompt integrity and custom compaction instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

_DATETIME_TAG_PATTERN = re.compile(
    r"^\s*<current_datetime>(.*?)</current_datetime>\s*",
    re.IGNORECASE | re.DOTALL,
)
_GENERIC_META_PATTERN = re.compile(
    r"^\s*<(?:client_env|session_meta|context_metadata)>(.*?)</(?:client_env|session_meta|context_metadata)>\s*",
    re.IGNORECASE | re.DOTALL,
)
_GREP_LINE_PATTERN = re.compile(r"^([^:<>=\s]+):(\d+):(.*)$")


class ContentCategory(StrEnum):
    """Semantic classification of message content."""

    USER_QUERY = "user_query"
    SEARCH_RESULTS = "search_results"
    STRUCTURED_LOGS = "structured_logs"
    GENERIC_TEXT = "generic_text"


class MetadataPrefixKind(StrEnum):
    """Type of client-injected metadata prefix detected."""

    DATETIME_TAG = "datetime_tag"
    GENERIC_META_TAG = "generic_meta_tag"
    NONE = "none"


@dataclass(slots=True, frozen=True)
class ParsedUserQuery:
    """Disambiguated and sanitized user prompt payload."""

    raw_content: str
    cleaned_prompt: str
    prefix_kind: MetadataPrefixKind
    extracted_metadata: dict[str, str] = field(default_factory=dict)
    is_safe_user_query: bool = True


@dataclass(slots=True, frozen=True)
class CompactionPromptFallbackContract:
    """Contract preserving custom compaction prompts in full-summarization fallbacks."""

    custom_prompt: str = ""
    default_fallback_prompt: str = "Summarize key accomplishments and current blockers."
    preserve_custom_in_fallback: bool = True
    max_summary_tokens: int = 2048

    def resolve_effective_prompt(self) -> str:
        """Resolve effective prompt strictly honoring custom prompt configuration."""
        if self.preserve_custom_in_fallback and self.custom_prompt.strip():
            return self.custom_prompt.strip()
        return self.default_fallback_prompt.strip()


class UserQueryDisambiguationGuard:
    """Guard and classifier ensuring human queries never get mistaken for tool outputs."""

    @classmethod
    def strip_metadata_prefixes(cls, content: str) -> ParsedUserQuery:
        """Strip client-injected XML metadata tags, returning the genuine user instruction."""
        metadata: dict[str, str] = {}
        cleaned = content

        # Check for <current_datetime>...</current_datetime>
        dt_match = _DATETIME_TAG_PATTERN.match(cleaned)
        if dt_match:
            metadata["current_datetime"] = dt_match.group(1).strip()
            cleaned = cleaned[dt_match.end() :].lstrip()
            prefix_kind = MetadataPrefixKind.DATETIME_TAG
        else:
            # Check for generic metadata tags
            meta_match = _GENERIC_META_PATTERN.match(cleaned)
            if meta_match:
                metadata["client_meta"] = meta_match.group(1).strip()
                cleaned = cleaned[meta_match.end() :].lstrip()
                prefix_kind = MetadataPrefixKind.GENERIC_META_TAG
            else:
                prefix_kind = MetadataPrefixKind.NONE

        return ParsedUserQuery(
            raw_content=content,
            cleaned_prompt=cleaned,
            prefix_kind=prefix_kind,
            extracted_metadata=metadata,
            is_safe_user_query=True,
        )

    @classmethod
    def _is_valid_grep_line(cls, line: str) -> bool:
        """Verify pre-colon segment is a plausible path, not a tag or key=value pair."""
        match = _GREP_LINE_PATTERN.match(line)
        if not match:
            return False
        path_part = match.group(1)
        # Path part must not contain angle brackets, quotes, or equal signs
        if any(c in path_part for c in ("<", ">", "=", '"', "'", ";")):
            return False
        # Must look like a file path or name (e.g. contains '.' or '/' or alphanumeric identifier)
        return len(path_part) > 1 and not path_part.startswith("-")

    @classmethod
    def classify_content(cls, content: str, *, is_human_turn: bool = True) -> ContentCategory:
        """Classify payload with absolute human-turn immunity and two-line grep floor."""
        # Immunity: Human/User turns are always classified as USER_QUERY
        if is_human_turn:
            return ContentCategory.USER_QUERY

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return ContentCategory.GENERIC_TEXT

        matching_grep_lines = sum(1 for line in lines if cls._is_valid_grep_line(line))

        # Absolute Two-Line Floor Gate: At least 2 lines must match grep format
        if matching_grep_lines >= 2 and (matching_grep_lines / len(lines) >= 0.30):
            return ContentCategory.SEARCH_RESULTS

        # Check for structured log formats (e.g., [INFO], [ERROR], timestamp prefixed)
        log_indicators = sum(
            1
            for line in lines
            if any(lvl in line.upper() for lvl in ("[INFO]", "[ERROR]", "[WARN]", "[DEBUG]", "FATAL:"))
        )
        if log_indicators >= 2 and (log_indicators / len(lines) >= 0.30):
            return ContentCategory.STRUCTURED_LOGS

        return ContentCategory.GENERIC_TEXT

    @classmethod
    def guard_compaction_prompt(cls, contract: CompactionPromptFallbackContract) -> str:
        """Guarantee custom compaction prompt survives automatic full-summarization fallbacks."""
        return contract.resolve_effective_prompt()
