"""Unit tests for User Query Disambiguation Guard & Compaction Prompt Preservation (Item 29)."""

from myrm_agent_harness.runtime.context.user_query_disambiguation_guard import (
    CompactionPromptFallbackContract,
    ContentCategory,
    MetadataPrefixKind,
    ParsedUserQuery,
    UserQueryDisambiguationGuard,
)


def test_strip_datetime_prefix_tag() -> None:
    """Verifies <current_datetime> tag is extracted into metadata and stripped from human query."""
    raw = "<current_datetime>2026-08-24T12:00:00Z</current_datetime> Please review and optimize auth module."
    parsed: ParsedUserQuery = UserQueryDisambiguationGuard.strip_metadata_prefixes(raw)

    assert parsed.prefix_kind == MetadataPrefixKind.DATETIME_TAG
    assert parsed.extracted_metadata.get("current_datetime") == "2026-08-24T12:00:00Z"
    assert parsed.cleaned_prompt == "Please review and optimize auth module."
    assert parsed.is_safe_user_query is True


def test_strip_generic_meta_tag() -> None:
    """Verifies generic client metadata tags are extracted and cleaned."""
    raw = "<client_env>platform=darwin arch=arm64</client_env> Run test suite"
    parsed = UserQueryDisambiguationGuard.strip_metadata_prefixes(raw)

    assert parsed.prefix_kind == MetadataPrefixKind.GENERIC_META_TAG
    assert parsed.extracted_metadata.get("client_meta") == "platform=darwin arch=arm64"
    assert parsed.cleaned_prompt == "Run test suite"

    # Plain text without tag
    plain = "Plain user question"
    parsed_plain = UserQueryDisambiguationGuard.strip_metadata_prefixes(plain)
    assert parsed_plain.prefix_kind == MetadataPrefixKind.NONE
    assert parsed_plain.cleaned_prompt == "Plain user question"


def test_human_turn_immunity_never_classified_as_search() -> None:
    """Verifies that human turns are 100% immune from being misclassified as tool search results."""
    # User message contains date-time and file:line notation
    user_msg_with_timestamps = (
        "<current_datetime>2026-08-24:12:30:45</current_datetime>\n"
        "Look at server.py:42: we need to handle NullPointerException.\n"
        "Also see client.py:100: fix the reconnect logic."
    )

    cat = UserQueryDisambiguationGuard.classify_content(user_msg_with_timestamps, is_human_turn=True)
    assert cat == ContentCategory.USER_QUERY


def test_valid_grep_search_results_classified_correctly() -> None:
    """Verifies genuine multi-line grep output from tools is accurately identified as SEARCH_RESULTS."""
    grep_tool_output = (
        "src/runtime/server.py:42:    def handle_request(req):\n"
        "src/runtime/server.py:45:        logger.info('Handling')\n"
        "src/runtime/client.py:88:    def send_request(req):\n"
    )

    cat = UserQueryDisambiguationGuard.classify_content(grep_tool_output, is_human_turn=False)
    assert cat == ContentCategory.SEARCH_RESULTS


def test_single_line_grep_or_tag_rejected_by_two_line_floor() -> None:
    """Verifies two-line floor and tag rejection prevent incidental matches from classifying as search."""
    # Accidental tag with colon
    accidental_tag_line = "<tag:42>: not a valid file path"
    cat_tag = UserQueryDisambiguationGuard.classify_content(accidental_tag_line, is_human_turn=False)
    assert cat_tag != ContentCategory.SEARCH_RESULTS

    # Only single-line match with extra text (below 2-line floor)
    single_line_match = (
        "Here is the explanation of the codebase architecture:\n"
        "app.py:10: single mention\n"
        "The rest is natural language prose describing the features.\n"
        "Nothing else matches grep format."
    )
    cat_single = UserQueryDisambiguationGuard.classify_content(single_line_match, is_human_turn=False)
    assert cat_single != ContentCategory.SEARCH_RESULTS


def test_custom_compaction_prompt_preserved_in_fallback() -> None:
    """Verifies user-defined compaction prompt survives fallback without being overwritten."""
    custom = "Specialized audit: focus strictly on security vulnerabilities and CVE status."
    default = "Generic summary"

    contract_with_custom = CompactionPromptFallbackContract(
        custom_prompt=custom,
        default_fallback_prompt=default,
        preserve_custom_in_fallback=True,
    )
    assert contract_with_custom.resolve_effective_prompt() == custom
    assert UserQueryDisambiguationGuard.guard_compaction_prompt(contract_with_custom) == custom

    # When custom is blank, safely fallback to default
    contract_blank = CompactionPromptFallbackContract(
        custom_prompt="",
        default_fallback_prompt=default,
        preserve_custom_in_fallback=True,
    )
    assert contract_blank.resolve_effective_prompt() == default
