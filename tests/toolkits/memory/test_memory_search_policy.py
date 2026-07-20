"""Tests for memory search policy ACL."""

from myrm_agent_harness.toolkits.memory.memory_search_policy import (
    MemorySearchPolicy,
    resolve_search_corpora,
)


def test_resolve_memory_only() -> None:
    corpora, reason = resolve_search_corpora("memory", MemorySearchPolicy())
    assert corpora == ["memory"]
    assert reason is None


def test_resolve_sessions_blocked_by_policy() -> None:
    corpora, reason = resolve_search_corpora("sessions", MemorySearchPolicy(allow_sessions=False))
    assert corpora == []
    assert reason is not None


def test_resolve_all_respects_policy_flags() -> None:
    corpora, reason = resolve_search_corpora(
        "all",
        MemorySearchPolicy(allow_wiki=True, allow_sessions=True),
    )
    assert corpora == ["memory", "wiki", "sessions"]
    assert reason is None


def test_resolve_all_skips_disabled_corpora() -> None:
    corpora, reason = resolve_search_corpora("all", MemorySearchPolicy(allow_wiki=False, allow_sessions=False))
    assert corpora == ["memory"]
    assert reason is None


def test_resolve_wiki_blocked_by_policy() -> None:
    corpora, reason = resolve_search_corpora("wiki", MemorySearchPolicy(allow_wiki=False))
    assert corpora == []
    assert reason is not None
    assert "Wiki" in reason


def test_resolve_wiki_allowed() -> None:
    corpora, reason = resolve_search_corpora("wiki", MemorySearchPolicy(allow_wiki=True))
    assert corpora == ["wiki"]
    assert reason is None


def test_resolve_sessions_allowed() -> None:
    corpora, reason = resolve_search_corpora("sessions", MemorySearchPolicy(allow_sessions=True))
    assert corpora == ["sessions"]
    assert reason is None


def test_resolve_unknown_corpus() -> None:
    corpora, reason = resolve_search_corpora("bogus", MemorySearchPolicy())  # type: ignore[arg-type]
    assert corpora == []
    assert reason is not None
    assert "Unknown corpus" in reason
