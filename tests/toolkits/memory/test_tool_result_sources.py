"""Tests for memory_search tool result source packing helpers."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.agent_surface.tool_result_sources import (
    pack_tool_result_with_sources,
    unpack_corpus_tool_result,
)


def test_pack_tool_result_with_sources_returns_plain_text_when_empty() -> None:
    assert pack_tool_result_with_sources("hello", []) == "hello"


def test_pack_tool_result_with_sources_embeds_metadata() -> None:
    packed = pack_tool_result_with_sources(
        "body",
        [{"type": "knowledge", "source_key": "wiki:1"}],
    )
    assert isinstance(packed, dict)
    assert packed["content"] == "body"
    metadata = packed["metadata"]
    assert isinstance(metadata, dict)
    sources = metadata["sources"]
    assert isinstance(sources, list)
    assert sources[0]["source_key"] == "wiki:1"


def test_unpack_corpus_tool_result_from_string() -> None:
    content, sources = unpack_corpus_tool_result("plain")
    assert content == "plain"
    assert sources == []


def test_unpack_corpus_tool_result_from_dict() -> None:
    content, sources = unpack_corpus_tool_result(
        {
            "content": "wrapped",
            "metadata": {"sources": [{"type": "conversation_history", "conversation_id": "c1"}]},
        }
    )
    assert content == "wrapped"
    assert len(sources) == 1
    assert sources[0]["conversation_id"] == "c1"
