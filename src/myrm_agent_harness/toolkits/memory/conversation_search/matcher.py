"""Exact phrase matcher and anchor context highlight extractor for conversation search.

Supports exact quoted phrases, multi-token boolean combinations, and context window
slicing for smooth anchor scroll and pulse glow animation targeting.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ContextHighlight: Highlighted snippet slice with character boundary offsets.
- ConversationExactSearchMatcher: Exact phrase and keyword matcher with context window extraction.

[POS]
Exact phrase matcher and anchor context highlight extractor for conversation search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_QUOTED_PHRASE_REGEX = re.compile(r'"([^"]+)"')


@dataclass(frozen=True)
class ContextHighlight:
    """Highlighted snippet slice with character boundary offsets."""

    prefix: str
    matched_text: str
    suffix: str
    start_char: int
    end_char: int

    def formatted_snippet(self) -> str:
        """Render snippet with highlight delimiters."""
        return f"{self.prefix}«{self.matched_text}»{self.suffix}".strip()


class ConversationExactSearchMatcher:
    """Exact phrase and keyword matcher with context window extraction."""

    @classmethod
    def parse_query_terms(cls, query: str) -> list[str]:
        """Extract quoted phrases and bare word tokens from query string."""
        if not query or not query.strip():
            return []

        cleaned = query.strip()
        quoted_matches = _QUOTED_PHRASE_REGEX.findall(cleaned)
        # Strip quoted matches to get remaining bare tokens
        remainder = _QUOTED_PHRASE_REGEX.sub(" ", cleaned)
        bare_tokens = [tok for tok in remainder.split() if tok.strip()]

        # Quoted exact phrases take priority, followed by distinct tokens
        terms: list[str] = [p.strip() for p in quoted_matches if p.strip()]
        for tok in bare_tokens:
            if tok not in terms:
                terms.append(tok)
        return terms

    @classmethod
    def matches(cls, text: str, query: str) -> bool:
        """Check whether text satisfies all terms in the query (AND semantic)."""
        if not text or not query:
            return False

        terms = cls.parse_query_terms(query)
        if not terms:
            return False

        lower_text = text.lower()
        return all(term.lower() in lower_text for term in terms)

    @classmethod
    def extract_highlight(
        cls,
        text: str,
        query: str,
        window_chars: int = 100,
    ) -> ContextHighlight | None:
        """Extract first matching term position and surrounding context slice."""
        if not text or not query:
            return None

        terms = cls.parse_query_terms(query)
        if not terms:
            return None

        lower_text = text.lower()
        first_match_idx: int = -1
        matched_term: str = ""

        # Locate first occurrence of any term
        for term in terms:
            idx = lower_text.find(term.lower())
            if idx != -1 and (first_match_idx == -1 or idx < first_match_idx):
                first_match_idx = idx
                matched_term = text[idx : idx + len(term)]

        if first_match_idx == -1:
            return None

        match_end_idx = first_match_idx + len(matched_term)

        # Slice prefix window
        prefix_start = max(0, first_match_idx - window_chars)
        raw_prefix = text[prefix_start:first_match_idx]
        prefix = f"...{raw_prefix}" if prefix_start > 0 else raw_prefix

        # Slice suffix window
        suffix_end = min(len(text), match_end_idx + window_chars)
        raw_suffix = text[match_end_idx:suffix_end]
        suffix = f"{raw_suffix}..." if suffix_end < len(text) else raw_suffix

        return ContextHighlight(
            prefix=prefix,
            matched_text=matched_term,
            suffix=suffix,
            start_char=first_match_idx,
            end_char=match_end_idx,
        )

    @classmethod
    def rank_and_score(cls, text: str, query: str) -> float:
        """Calculate relevance score between 0.0 and 1.0 based on phrase completeness."""
        if not text or not query:
            return 0.0

        terms = cls.parse_query_terms(query)
        if not terms:
            return 0.0

        lower_text = text.lower()
        matched_count = sum(1 for term in terms if term.lower() in lower_text)
        if matched_count == 0:
            return 0.0

        ratio = float(matched_count / len(terms))

        # Full exact query substring match bonus (supports unquoted term phrase match)
        clean_bare = query.strip().strip('"').lower()
        normalized_query = " ".join(terms).lower()
        if (
            query.strip().lower() in lower_text
            or (clean_bare and clean_bare in lower_text)
            or (normalized_query and normalized_query in lower_text)
        ):
            return min(1.0, 0.7 + 0.3 * ratio)

        return min(0.95, 0.5 * ratio)
