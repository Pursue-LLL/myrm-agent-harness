"""Comprehensive unit tests for InvalidGeneratedTitleRecoverySuite.

[INPUT]
- title_recovery types, taxonomy classifier, retry gate, and facade suite.

[OUTPUT]
- Deterministic verification of CoT leak rejection, option menu rejection,
  first-person prose stripping, provisional retry delay, and capped deterministic fallback.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_invalid_generated_title_recovery_suite.py
"""

from typing import Dict, List

import pytest

from myrm_agent_harness.agent import (
    InvalidGeneratedTitleRecoverySuite as RootExportedSuite,
)
from myrm_agent_harness.agent.context_management import (
    InvalidGeneratedTitleRecoverySuite,
    InvalidTitleReason,
    InvalidTitleTaxonomy,
    ProvisionalTitleRetryGate,
    TitleRecoveryConfig,
    TitleRecoveryState,
    TitleRecoveryVerdict,
    TitleValidationResult,
)


def test_taxonomy_detects_cot_and_thinking_leaks() -> None:
    """Verifies that reasoning tokens and <think> blocks are strictly classified as invalid."""
    taxonomy = InvalidTitleTaxonomy(TitleRecoveryConfig())

    cot_cases = [
        "<think>The user wants a script to parse logs</think>Log Parser",
        "<thought>Thinking about this...</thought>API Design",
        "Thinking Process: First let's summarize the conversation into a title",
        "Thought: A good title would be Database Optimization",
    ]

    for raw in cot_cases:
        res = taxonomy.validate_and_cleanse(raw)
        assert res.is_valid is False
        assert InvalidTitleReason.COT_LEAK in res.reasons


def test_taxonomy_detects_option_menus() -> None:
    """Verifies that multiple choice and numbered candidate menus are rejected."""
    taxonomy = InvalidTitleTaxonomy(TitleRecoveryConfig())

    menu_cases = [
        "Option 1: User Login\nOption 2: Auth Flow",
        "1. Fix Database Connection\n2. Database Reconnect",
        "Here are three titles: Web Scraping, Parser, Crawler",
        "以下是几个可选标题：1. 性能优化 2. 内存分析",
    ]

    for raw in menu_cases:
        res = taxonomy.validate_and_cleanse(raw)
        assert res.is_valid is False
        assert InvalidTitleReason.OPTION_MENU in res.reasons


def test_taxonomy_cleanses_conversational_prose_and_prefixes() -> None:
    """Verifies that conversational wrappers and label prefixes are cleanly stripped."""
    taxonomy = InvalidTitleTaxonomy(TitleRecoveryConfig(min_length=3, max_length=50))

    # Case 1: Superficial conversational wrapper that can be cleaned to valid title
    res1 = taxonomy.validate_and_cleanse("Title: Python AST Parser")
    assert res1.is_valid is True
    assert res1.cleaned_title == "Python AST Parser"

    res2 = taxonomy.validate_and_cleanse("标题：Docker 部署方案")
    assert res2.is_valid is True
    assert res2.cleaned_title == "Docker 部署方案"

    res3 = taxonomy.validate_and_cleanse("Here is a title: Stripe Webhook Integration")
    assert res3.is_valid is True
    assert res3.cleaned_title == "Stripe Webhook Integration"

    res4 = taxonomy.validate_and_cleanse('“React Virtualized Table”')
    assert res4.is_valid is True
    assert res4.cleaned_title == "React Virtualized Table"


def test_taxonomy_rejects_empty_code_and_garbage() -> None:
    """Verifies that empty strings, pure punctuation, and markdown code wraps are rejected."""
    taxonomy = InvalidTitleTaxonomy(TitleRecoveryConfig(min_length=2))

    assert taxonomy.validate_and_cleanse("").is_valid is False
    assert taxonomy.validate_and_cleanse("   ").is_valid is False
    assert taxonomy.validate_and_cleanse("```python\nprint('hello')\n```").is_valid is False
    assert taxonomy.validate_and_cleanse("!@#$%^&*()_+").is_valid is False


def test_provisional_retry_gate_heals_on_subsequent_turn() -> None:
    """Verifies that an initial dirty title is deferred, and heals cleanly on a later exchange."""
    gate = ProvisionalTitleRetryGate(TitleRecoveryConfig(max_recovery_exchanges=3))
    session_id = "test-session-healing-001"
    fallback_content = "User: How do I configure Nginx for WebSocket proxying?"

    # Turn 1: Model outputs CoT leak -> Rejected, deferred as provisional, not finalized
    verdict1, title1, val1 = gate.evaluate_title_candidate(
        session_id=session_id,
        raw_candidate="<think>Need to generate title</think>Nginx Config",
        fallback_content=fallback_content,
    )
    assert verdict1 == TitleRecoveryVerdict.RETRY_LATER_PROVISIONAL
    assert title1 == "Untitled Chat"
    assert val1.is_valid is False

    state1 = gate.get_state(session_id)
    assert state1 is not None
    assert state1.exchange_count == 1
    assert state1.is_finalized is False

    # Turn 2: Subsequent assistant exchange outputs clean title -> Heals and finalizes!
    verdict2, title2, val2 = gate.evaluate_title_candidate(
        session_id=session_id,
        raw_candidate="Nginx WebSocket Proxy",
        fallback_content=fallback_content,
    )
    assert verdict2 == TitleRecoveryVerdict.ACCEPTED_CLEAN
    assert title2 == "Nginx WebSocket Proxy"
    assert val2.is_valid is True

    state2 = gate.get_state(session_id)
    assert state2 is not None
    assert state2.exchange_count == 1
    assert state2.is_finalized is True
    assert state2.current_title == "Nginx WebSocket Proxy"


def test_provisional_retry_gate_caps_out_to_deterministic_fallback() -> None:
    """Verifies that hitting max recovery exchanges triggers deterministic fallback and finalizes."""
    gate = ProvisionalTitleRetryGate(
        TitleRecoveryConfig(max_recovery_exchanges=2, fallback_preview_length=20)
    )
    session_id = "test-session-fallback-002"
    fallback_content = "User: Optimize Postgres query latency for partitioned tables"

    # Turn 1: Invalid menu format -> Retry later
    v1, t1, _ = gate.evaluate_title_candidate(
        session_id, "1. Option A\n2. Option B", fallback_content
    )
    assert v1 == TitleRecoveryVerdict.RETRY_LATER_PROVISIONAL
    assert t1 == "Untitled Chat"

    # Turn 2: Exchange cap (2) reached with another invalid candidate -> Fallback finalized
    v2, t2, _ = gate.evaluate_title_candidate(
        session_id, "Option 1: Fast Query", fallback_content
    )
    assert v2 == TitleRecoveryVerdict.FALLBACK_FINALIZED
    assert "Optimize Postgres" in t2
    assert t2.endswith("...")

    state = gate.get_state(session_id)
    assert state is not None
    assert state.is_finalized is True
    assert state.exchange_count == 2


def test_suite_facade_and_root_exports() -> None:
    """Verifies facade operations and root level lazy export integrity."""
    suite = InvalidGeneratedTitleRecoverySuite()
    session_id = "test-facade-session"

    assert suite.is_valid_title("GraphQL Schema Migration") is True
    assert suite.is_valid_title("<think>bad title</think>") is False

    fallback = suite.generate_fallback("User: Build a compiler for ToyLang")
    assert "Build a compiler" in fallback

    # Verify root exported suite
    assert RootExportedSuite is InvalidGeneratedTitleRecoverySuite
    inst = RootExportedSuite()
    assert isinstance(inst, InvalidGeneratedTitleRecoverySuite)
    assert inst.taxonomy is not None
    assert inst.gate is not None
