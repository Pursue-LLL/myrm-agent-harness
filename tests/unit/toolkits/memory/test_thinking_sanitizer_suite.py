"""[POS]: tests/unit/toolkits/memory/test_thinking_sanitizer_suite.py
[INPUT]: ThinkingBlockSanitizer and related configurations.
[OUTPUT]: Pytest test cases validating paired tag scrubbing, orphan close rescue, unclosed tag protection, and egress guards.
"""

from myrm_agent_harness.toolkits.memory import (
    SanitizationResult,
    ThinkingBlockSanitizer,
    ThinkingSanitizerConfig,
)


def test_paired_thinking_tags_scrubbing() -> None:
    """Validate paired <think> and <thought> tags are cleanly stripped."""
    sanitizer = ThinkingBlockSanitizer()
    raw_text = (
        "<think>\n"
        "Wait, the user wants a summary of the database migration.\n"
        "Let me see: we changed SQLite to Postgres and added WAL mode.\n"
        "</think>\n"
        "The database migration upgraded the schema to PostgreSQL with WAL mode enabled."
    )

    result = sanitizer.sanitize(raw_text)
    assert isinstance(result, SanitizationResult)
    assert result.has_thinking_markers is True
    assert result.has_unclosed_tags is False
    assert result.stripped_markers_count >= 1
    assert result.is_usable is True
    assert "<think>" not in result.cleaned_text
    assert "</think>" not in result.cleaned_text
    assert "The database migration upgraded the schema" in result.cleaned_text

    # Verify is_usable_summary egress guard returns clean text
    clean_summary = sanitizer.is_usable_summary(raw_text)
    assert clean_summary is not None
    assert clean_summary == result.cleaned_text


def test_orphan_close_tag_rescue() -> None:
    """Validate orphan </think> tag strips pre-close draft and preserves post-close conclusions."""
    sanitizer = ThinkingBlockSanitizer()
    # LLM started draft without open tag, truncated/drifted, then emitted </think> before final response
    raw_text = (
        "I need to evaluate whether the token cache is working.\n"
        "Let me double check the logs and memory footprints.\n"
        "</think>\n"
        "The cache hit ratio reached 94.2% after prompt normalization."
    )

    result = sanitizer.sanitize(raw_text)
    assert result.has_thinking_markers is True
    assert result.is_usable is True
    assert "</think>" not in result.cleaned_text
    assert "I need to evaluate" not in result.cleaned_text
    assert result.cleaned_text == "The cache hit ratio reached 94.2% after prompt normalization."


def test_unclosed_open_tag_protection() -> None:
    """Validate unclosed <think> tag drops thinking buffer and guards against leakage."""
    sanitizer = ThinkingBlockSanitizer(
        ThinkingSanitizerConfig(min_usable_chars=10, drop_unclosed_tags=True)
    )
    raw_text = (
        "Initial note.\n"
        "<think>\n"
        "Thinking process truncated by max_tokens limit without closing tag..."
    )

    result = sanitizer.sanitize(raw_text)
    assert result.has_unclosed_tags is True
    assert result.has_thinking_markers is True
    # Initial note is 13 chars >= 10
    assert "<think>" not in result.cleaned_text
    assert "Thinking process truncated" not in result.cleaned_text
    assert result.cleaned_text == "Initial note."
    assert result.is_usable is True

    # When whole text is unclosed think draft
    pure_unclosed = "<think>Just drafting some thoughts..."
    pure_result = sanitizer.sanitize(pure_unclosed)
    assert pure_result.has_unclosed_tags is True
    assert pure_result.is_usable is False
    assert pure_result.cleaned_text == ""
    assert sanitizer.is_usable_summary(pure_unclosed) is None


def test_planning_leadin_stripping() -> None:
    """Validate common meta-talk lead-in sentences are scrubbed."""
    sanitizer = ThinkingBlockSanitizer()
    raw_text = (
        "I need to create a thorough summary of this conversation.\n"
        "User completed the payment gateway integration with Stripe."
    )

    result = sanitizer.sanitize(raw_text)
    assert result.is_usable is True
    assert "I need to create a thorough summary" not in result.cleaned_text
    assert result.cleaned_text == "User completed the payment gateway integration with Stripe."


def test_egress_guard_omits_substandard_content() -> None:
    """Validate is_usable_summary returns None for empty, short, or invalid text."""
    sanitizer = ThinkingBlockSanitizer(ThinkingSanitizerConfig(min_usable_chars=15))

    # 1. Empty and whitespace
    assert sanitizer.is_usable_summary("") is None
    assert sanitizer.is_usable_summary("   \n\t  ") is None

    # 2. Pure think block
    pure_think = "<think>I am wondering what to write here.</think>"
    assert sanitizer.is_usable_summary(pure_think) is None

    # 3. Text below minimum length threshold
    short_text = "Too short."
    assert sanitizer.is_usable_summary(short_text) is None

    # 4. Valid text passes
    valid_text = "This is a sufficiently long and actionable summary of session progress."
    assert sanitizer.is_usable_summary(valid_text) == valid_text
