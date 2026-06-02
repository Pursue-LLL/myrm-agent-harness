"""Tests for compression_formatting module."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import CompactToolCall
from myrm_agent_harness.agent.context_management.strategies.compression_formatting import (
    _try_extract_from_args,
    extract_identifier,
    generate_compressed_content,
    generate_compressed_content_with_stats,
    generate_generic_compressed_content,
    shrink_tool_call_args,
)


def _make_compact(
    tool_name: str = "test_tool",
    identifier: str = "test_id",
    original_tokens: int = 100,
    evicted_path: str | None = None,
) -> CompactToolCall:
    return CompactToolCall(
        tool_name=tool_name,
        identifier=identifier,
        identifier_type="other",
        timestamp="2026-01-01T00:00:00",
        original_tokens=original_tokens,
        evicted_path=evicted_path,
    )


def _make_tool_msg(tool_call_id: str = "tc1", content: str = "ok") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id)


def _make_ai_msg(tool_call_id: str = "tc1", args: dict[str, object] | None = None) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": tool_call_id, "name": "test", "args": args or {}}])


# --- _try_extract_from_args ---


class TestTryExtractFromArgs:
    def test_string_value(self) -> None:
        assert _try_extract_from_args({"url": "https://example.com"}, "url") == "https://example.com"

    def test_empty_value(self) -> None:
        assert _try_extract_from_args({"url": ""}, "url") is None

    def test_missing_key(self) -> None:
        assert _try_extract_from_args({}, "url") is None

    def test_list_value(self) -> None:
        result = _try_extract_from_args({"paths": ["/a", "/b", "/c", "/d"]}, "paths")
        assert result == "/a, /b, /c"

    def test_truncates_long_string(self) -> None:
        long_val = "x" * 300
        result = _try_extract_from_args({"path": long_val}, "path")
        assert result is not None
        assert len(result) == 200


# --- extract_identifier ---


class TestExtractIdentifier:
    def test_from_compact_rule_arg(self) -> None:
        tool_msg = _make_tool_msg("tc1")
        ai_msg = _make_ai_msg("tc1", {"path": "/src/main.py"})
        assert extract_identifier(tool_msg, ai_msg, "path") == "/src/main.py"

    def test_fallback_to_priority_list(self) -> None:
        """When identifier_arg not found, falls back to priority-based extraction."""
        tool_msg = _make_tool_msg("tc1")
        ai_msg = _make_ai_msg("tc1", {"url": "https://api.example.com", "other": "irrelevant"})
        result = extract_identifier(tool_msg, ai_msg, "nonexistent_arg")
        assert result == "https://api.example.com"

    def test_priority_order(self) -> None:
        """url has higher priority than command."""
        tool_msg = _make_tool_msg("tc1")
        ai_msg = _make_ai_msg("tc1", {"command": "ls -la", "url": "https://top.com"})
        result = extract_identifier(tool_msg, ai_msg, "missing")
        assert result == "https://top.com"

    def test_command_fallback(self) -> None:
        """Falls back to command when no higher-priority key exists."""
        tool_msg = _make_tool_msg("tc1")
        ai_msg = _make_ai_msg("tc1", {"command": "npm test", "random_param": "xyz"})
        result = extract_identifier(tool_msg, ai_msg, "missing")
        assert result == "npm test"

    def test_no_args_match_returns_tool_call_id(self) -> None:
        tool_msg = _make_tool_msg("tc1")
        ai_msg = _make_ai_msg("tc1", {"random": "data"})
        result = extract_identifier(tool_msg, ai_msg, "missing")
        assert result == "tool_call_tc1"

    def test_no_ai_msg_returns_tool_call_id(self) -> None:
        tool_msg = _make_tool_msg("tc1")
        result = extract_identifier(tool_msg, None, "path")
        assert result == "tool_call_tc1"

    def test_artifact_fallback(self) -> None:
        tool_msg = _make_tool_msg("tc1")
        tool_msg.artifact = {"path": "/from/artifact"}
        result = extract_identifier(tool_msg, None, "path")
        assert result == "/from/artifact"

    def test_list_identifier(self) -> None:
        tool_msg = _make_tool_msg("tc1")
        ai_msg = _make_ai_msg("tc1", {"paths": ["/a.py", "/b.py"]})
        result = extract_identifier(tool_msg, ai_msg, "paths")
        assert result == "/a.py, /b.py"


# --- generate_compressed_content ---


class TestGenerateCompressedContent:
    def test_basic(self) -> None:
        info = _make_compact(identifier="test.py")
        result = generate_compressed_content(info, "COMPACTED: file_read\nPATH: {identifier}")
        assert "PATH: test.py" in result
        assert "META: tokens_saved=100" in result

    def test_with_evicted_path(self) -> None:
        info = _make_compact(evicted_path="offload/123.txt")
        result = generate_compressed_content(info, "COMPACTED: {identifier}")
        assert "FILE:" in result
        assert "RECOVER:" in result
        assert "LIFECYCLE:" in result


# --- generate_compressed_content_with_stats ---


class TestGenerateCompressedContentWithStats:
    def test_basic(self) -> None:
        info = _make_compact(identifier="test.py")
        stats = {"lines": 50, "chars": 1200}
        tpl = "COMPACTED: file_read\nPATH: {identifier}\nRESULT: {lines} lines, {chars} chars"
        result = generate_compressed_content_with_stats(info, tpl, stats)
        assert "50 lines" in result
        assert "1200 chars" in result

    def test_missing_template_key_degrades(self) -> None:
        info = _make_compact(identifier="test.py")
        stats = {"lines": 50}
        tpl = "COMPACTED: {identifier}\nRESULT: {missing_key}"
        result = generate_compressed_content_with_stats(info, tpl, stats)
        assert "COMPACTED: test_tool" in result
        assert "ID: test.py" in result


# --- generate_generic_compressed_content ---


class TestGenerateGenericCompressedContent:
    def test_without_stats(self) -> None:
        info = _make_compact(tool_name="mcp_tool", identifier="https://api.com")
        result = generate_generic_compressed_content(info)
        assert "COMPACTED: mcp_tool" in result
        assert "ID: https://api.com" in result
        assert "RESULT:" not in result

    def test_with_stats(self) -> None:
        info = _make_compact(tool_name="mcp_tool", identifier="https://api.com")
        stats = {"chars": 5000, "lines": 120}
        result = generate_generic_compressed_content(info, stats)
        assert "RESULT: 5000 chars, 120 lines" in result

    def test_with_stats_partial(self) -> None:
        info = _make_compact()
        stats = {"chars": 300}
        result = generate_generic_compressed_content(info, stats)
        assert "300 chars" in result
        assert "? lines" in result

    def test_with_evicted_path(self) -> None:
        info = _make_compact(evicted_path="offload/abc.txt")
        result = generate_generic_compressed_content(info)
        assert "FILE:" in result
        assert "RECOVER:" in result

    def test_empty_stats_dict_no_result_line(self) -> None:
        info = _make_compact()
        result = generate_generic_compressed_content(info, {})
        assert "RESULT:" not in result


# --- shrink_tool_call_args ---


class TestShrinkToolCallArgs:
    def test_short_args_unchanged(self) -> None:
        tcs = [{"id": "1", "name": "t", "args": {"cmd": "ls"}}]
        result = shrink_tool_call_args(tcs)
        assert result[0]["args"]["cmd"] == "ls"

    def test_long_string_truncated(self) -> None:
        long_content = "x" * 1000
        tcs = [{"id": "1", "name": "t", "args": {"content": long_content}}]
        result = shrink_tool_call_args(tcs)
        assert "chars omitted" in result[0]["args"]["content"]

    def test_no_args_key(self) -> None:
        tcs = [{"id": "1", "name": "t"}]
        result = shrink_tool_call_args(tcs)
        assert result == tcs

    def test_non_dict_args(self) -> None:
        tcs = [{"id": "1", "name": "t", "args": "raw_string"}]
        result = shrink_tool_call_args(tcs)
        assert result[0]["args"] == "raw_string"

    def test_large_list_truncated(self) -> None:
        big_list = list(range(30))
        tcs = [{"id": "1", "name": "t", "args": {"items": big_list}}]
        result = shrink_tool_call_args(tcs)
        items = result[0]["args"]["items"]
        assert len(items) == 11
        assert "more items omitted" in items[-1]

    def test_nested_dict(self) -> None:
        long_val = "y" * 600
        tcs = [{"id": "1", "name": "t", "args": {"nested": {"deep": long_val}}}]
        result = shrink_tool_call_args(tcs)
        assert "chars omitted" in result[0]["args"]["nested"]["deep"]

    def test_does_not_mutate_original(self) -> None:
        original = [{"id": "1", "name": "t", "args": {"content": "a" * 1000}}]
        shrink_tool_call_args(original)
        assert len(original[0]["args"]["content"]) == 1000
