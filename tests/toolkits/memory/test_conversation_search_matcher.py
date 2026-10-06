"""Unit tests for ConversationExactSearchMatcher and ContextHighlight.

Validates exact quoted phrase parsing, multi-token boolean AND matching,
context window slicing with character boundary offsets, and relevance scoring.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory import (
    ContextHighlight,
    ConversationExactSearchMatcher,
)


class TestConversationExactSearchMatcher:
    """Test suite for ConversationExactSearchMatcher."""

    def test_parse_query_terms_quoted_and_bare(self) -> None:
        query = 'deploy "Python 3.12" cluster "Helm chart" production'
        terms = ConversationExactSearchMatcher.parse_query_terms(query)
        assert terms == ["Python 3.12", "Helm chart", "deploy", "cluster", "production"]

    def test_parse_query_terms_empty(self) -> None:
        assert ConversationExactSearchMatcher.parse_query_terms("") == []
        assert ConversationExactSearchMatcher.parse_query_terms("   ") == []

    def test_matches_exact_phrase(self) -> None:
        text = "We decided to migrate our backend to Python 3.12 last week."
        assert ConversationExactSearchMatcher.matches(text, '"Python 3.12"') is True
        assert ConversationExactSearchMatcher.matches(text, '"Python 3.11"') is False

    def test_matches_multi_token_and(self) -> None:
        text = "We use FastAPI with Postgres database for real-time messaging."
        assert ConversationExactSearchMatcher.matches(text, "FastAPI Postgres messaging") is True
        assert ConversationExactSearchMatcher.matches(text, "FastAPI Redis") is False

    def test_matches_case_insensitive(self) -> None:
        text = "CONFIG_KEY_URL is set to localhost:8000"
        assert ConversationExactSearchMatcher.matches(text, "config_key_url localhost") is True

    def test_extract_highlight_bounded_window(self) -> None:
        prefix_lead = "A" * 150
        target = "TARGET_TOKEN"
        suffix_tail = "B" * 150
        full_text = f"{prefix_lead} {target} {suffix_tail}"

        highlight = ConversationExactSearchMatcher.extract_highlight(
            full_text, target, window_chars=50
        )
        assert isinstance(highlight, ContextHighlight)
        assert highlight.matched_text == target
        assert highlight.prefix.startswith("...")
        assert highlight.suffix.endswith("...")
        assert len(highlight.prefix) <= 55
        assert len(highlight.suffix) <= 55
        assert highlight.start_char == 151
        assert highlight.end_char == 151 + len(target)

        # Verify formatted snippet output
        snippet = highlight.formatted_snippet()
        assert f"«{target}»" in snippet

    def test_extract_highlight_near_boundaries(self) -> None:
        text = "Short text with TOKEN here"
        highlight = ConversationExactSearchMatcher.extract_highlight(text, "TOKEN", window_chars=50)
        assert highlight is not None
        assert not highlight.prefix.startswith("...")
        assert not highlight.suffix.endswith("...")
        assert highlight.matched_text == "TOKEN"

    def test_extract_highlight_not_found(self) -> None:
        text = "Some random dialogue"
        assert ConversationExactSearchMatcher.extract_highlight(text, "MISSING") is None
        assert ConversationExactSearchMatcher.extract_highlight("", "TOKEN") is None

    def test_rank_and_score(self) -> None:
        text = "Building async workers with Python 3.12 and uv"
        score_exact = ConversationExactSearchMatcher.rank_and_score(
            text, "Python 3.12"
        )
        assert score_exact >= 0.7

        score_partial = ConversationExactSearchMatcher.rank_and_score(
            text, "Python Ruby"
        )
        assert 0.0 < score_partial < score_exact

        score_zero = ConversationExactSearchMatcher.rank_and_score(text, "Golang Rust")
        assert score_zero == 0.0
