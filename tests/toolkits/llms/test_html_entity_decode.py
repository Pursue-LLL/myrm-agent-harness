"""Tests for xAI/Grok HTML entity decoding in tool call arguments.

xAI/Grok models encode special characters as HTML entities inside tool call
argument values (e.g. ``&&`` → ``&amp;&amp;``). This corrupts shell commands
and other string values. The decoding is applied *after* JSON parsing, so
the JSON structure itself is never affected.
"""

import json

import pytest

from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import (
    HTML_ENTITY_RE,
    decode_html_entities_in_args,
    decode_html_entities_str,
)

# ── decode_html_entities_str ─────────────────────────────────────────


class TestDecodeHtmlEntitiesStr:
    def test_amp(self) -> None:
        assert decode_html_entities_str("a &amp; b") == "a & b"

    def test_double_amp(self) -> None:
        assert decode_html_entities_str("cmd1 &amp;&amp; cmd2") == "cmd1 && cmd2"

    def test_lt_gt(self) -> None:
        assert decode_html_entities_str("&lt;div&gt;") == "<div>"

    def test_quot(self) -> None:
        assert decode_html_entities_str("say &quot;hello&quot;") == 'say "hello"'

    def test_apos(self) -> None:
        assert decode_html_entities_str("it&apos;s") == "it's"

    def test_numeric_apos(self) -> None:
        assert decode_html_entities_str("it&#39;s") == "it's"

    def test_no_entities(self) -> None:
        assert decode_html_entities_str("plain text") == "plain text"

    def test_mixed(self) -> None:
        result = decode_html_entities_str("echo &quot;ok&quot; &amp;&amp; cat &lt;f&gt;")
        assert result == 'echo "ok" && cat <f>'


# ── decode_html_entities_in_args (recursive) ─────────────────────────


class TestDecodeHtmlEntitiesInArgs:
    def test_flat_dict(self) -> None:
        obj = {"cmd": "a &amp;&amp; b", "count": 3}
        result = decode_html_entities_in_args(obj)
        assert result == {"cmd": "a && b", "count": 3}

    def test_nested_dict(self) -> None:
        obj = {"outer": {"inner": "&lt;tag&gt;"}}
        result = decode_html_entities_in_args(obj)
        assert result == {"outer": {"inner": "<tag>"}}

    def test_list_values(self) -> None:
        obj = {"args": ["a &amp; b", "c &lt; d"]}
        result = decode_html_entities_in_args(obj)
        assert result == {"args": ["a & b", "c < d"]}

    def test_no_entities_passthrough(self) -> None:
        obj = {"query": "SELECT 1", "limit": 10}
        assert decode_html_entities_in_args(obj) == obj

    def test_none_passthrough(self) -> None:
        assert decode_html_entities_in_args(None) is None

    def test_bool_passthrough(self) -> None:
        assert decode_html_entities_in_args(True) is True

    def test_int_passthrough(self) -> None:
        assert decode_html_entities_in_args(42) == 42

    def test_string_with_entities(self) -> None:
        assert decode_html_entities_in_args("a &amp; b") == "a & b"

    def test_string_without_entities(self) -> None:
        assert decode_html_entities_in_args("plain") == "plain"


# ── HTML_ENTITY_RE ───────────────────────────────────────────────────


class TestHtmlEntityRegex:
    @pytest.mark.parametrize(
        "text",
        ["&amp;", "&lt;", "&gt;", "&quot;", "&apos;", "&#39;", "&#x2F;", "&#123;"],
    )
    def test_matches_entities(self, text: str) -> None:
        assert HTML_ENTITY_RE.search(text)

    @pytest.mark.parametrize("text", ["plain", "a & b", "3 < 4", "hello"])
    def test_no_match_on_plain(self, text: str) -> None:
        assert HTML_ENTITY_RE.search(text) is None


# ── Integration with _parse_tool_call_args ───────────────────────────


class TestParseToolCallArgsIntegration:
    """End-to-end: JSON string → parsed dict with entities decoded."""

    @pytest.fixture(autouse=True)
    def _import_parser(self) -> None:
        from myrm_agent_harness.toolkits.llms.adapters.converters import (
            _parse_tool_call_args,
        )

        self.parse = _parse_tool_call_args

    def test_xai_bash_command(self) -> None:
        raw = json.dumps({"command": "source .env &amp;&amp; psql", "timeout": 30})
        result = self.parse(raw, "bash_tool")
        assert result["command"] == "source .env && psql"
        assert result["timeout"] == 30

    def test_normal_args_unchanged(self) -> None:
        raw = json.dumps({"query": "SELECT * FROM users", "limit": 10})
        result = self.parse(raw, "sql_tool")
        assert result["query"] == "SELECT * FROM users"

    def test_dict_input_decoded(self) -> None:
        result = self.parse({"path": "/home/user &amp; files"}, "file_tool")
        assert result["path"] == "/home/user & files"

    def test_dict_input_no_entities(self) -> None:
        data = {"query": "SELECT 1", "count": 42}
        result = self.parse(data, "sql_tool")
        assert result == data

    def test_nested_xai_values(self) -> None:
        raw = json.dumps({"cmd": "echo &quot;hi&quot; &amp;&amp; ls", "flag": True})
        result = self.parse(raw, "bash_tool")
        assert result["cmd"] == 'echo "hi" && ls'
        assert result["flag"] is True
