"""Tests for streaming citation marker audit."""

from myrm_agent_harness.agent.streaming.citation_audit import audit_citation_markers, resolve_source_count_for_audit


def test_audit_citation_markers_empty_when_no_markers() -> None:
    result = audit_citation_markers("plain text", 3)
    assert result.total_markers == 0
    assert result.valid == 0
    assert result.unresolved == 0


def test_audit_citation_markers_counts_valid_and_unresolved() -> None:
    result = audit_citation_markers("A【1】 B【2】 C【9】", 2)
    assert result.total_markers == 3
    assert result.valid == 2
    assert result.unresolved == 1


def test_resolve_source_count_for_audit_uses_max_index() -> None:
    sources: list[dict[str, object]] = [{"index": 1}, {"index": 5}]
    assert resolve_source_count_for_audit(sources) == 5
