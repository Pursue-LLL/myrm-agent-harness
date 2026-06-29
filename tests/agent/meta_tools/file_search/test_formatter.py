"""Tests for grep result formatter."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.file_search._formatter import (
    MAX_LINE_CHARS,
    NON_CODE_MATCH_CAP,
    _DENSIFY_MIN_MATCHES,
    compact_match_line,
    format_grep_results,
)


class TestCompactMatchLine:
    def test_short_line_unchanged(self) -> None:
        line = "def hello(): pass"
        assert compact_match_line(line, "hello", False) == line

    def test_exactly_max_chars_unchanged(self) -> None:
        line = "x" * MAX_LINE_CHARS
        assert compact_match_line(line, "x", False) == line

    def test_long_line_truncated(self) -> None:
        line = "a" * 500
        result = compact_match_line(line, "a", False)
        assert len(result) < 500
        assert "truncated" in result

    def test_match_centering_non_regex(self) -> None:
        line = "a" * 200 + "TARGET" + "b" * 300
        result = compact_match_line(line, "TARGET", is_regex=False)
        assert "TARGET" in result
        assert "truncated" in result

    def test_regex_pattern_starts_from_beginning(self) -> None:
        line = "a" * 500
        result = compact_match_line(line, r"\w+", is_regex=True)
        assert result.startswith("a")
        assert "truncated" in result

    def test_truncation_prefix_only(self) -> None:
        line = "a" * 300
        result = compact_match_line(line, "a", is_regex=True)
        assert "\u2026" in result or "truncated" in result

    def test_empty_pattern(self) -> None:
        line = "x" * 500
        result = compact_match_line(line, "", is_regex=False)
        assert "truncated" in result


class TestFormatGrepResults:
    def test_no_results(self) -> None:
        output = format_grep_results([], "test", 10, 100)
        assert "No matches found" in output

    def test_flat_output(self) -> None:
        results = [
            {"file": "a.py", "line": 5, "content": "hello world"},
            {"file": "b.py", "line": 10, "content": "hello again"},
        ]
        output = format_grep_results(results, "hello", 20, 100)
        assert "a.py:5: hello world" in output
        assert "b.py:10: hello again" in output
        assert "Found 2 match(es)" in output

    def test_non_code_file_capping(self) -> None:
        matches = [{"file": "config.json", "line": i, "content": f'"key": {i}'} for i in range(10)]
        output = format_grep_results(matches, "key", 1, 100)
        visible_lines = [ln for ln in output.split("\n") if "config.json" in ln and ":" in ln and "omitted" not in ln]
        assert len(visible_lines) <= NON_CODE_MATCH_CAP
        assert "non-code matches omitted" in output

    def test_max_results_limit_message(self) -> None:
        results = [{"file": "a.py", "line": i, "content": "match"} for i in range(5)]
        output = format_grep_results(results, "match", 10, 5)
        assert "limited to first 5" in output

    def test_long_line_truncation_in_output(self) -> None:
        long_content = "x" * 500
        results = [{"file": "a.py", "line": 10, "content": long_content}]
        output = format_grep_results(results, "x", 5, 100)
        assert "truncated" in output

    def test_non_code_lock_file_capped(self) -> None:
        matches = [{"file": "yarn.lock", "line": i, "content": f"pkg@{i}"} for i in range(10)]
        output = format_grep_results(matches, "pkg", 1, 100)
        assert "non-code matches omitted" in output

    def test_non_code_log_file_capped(self) -> None:
        matches = [{"file": "app.log", "line": i, "content": f"ERROR {i}"} for i in range(10)]
        output = format_grep_results(matches, "ERROR", 1, 100)
        assert "non-code matches omitted" in output

    def test_non_code_svg_file_capped(self) -> None:
        matches = [{"file": "icon.svg", "line": i, "content": f"<path d='{i}'/>"} for i in range(10)]
        output = format_grep_results(matches, "path", 1, 100)
        assert "non-code matches omitted" in output

    def test_code_file_not_capped(self) -> None:
        matches = [{"file": "service.py", "line": i, "content": f"x = {i}"} for i in range(10)]
        output = format_grep_results(matches, "x", 1, 100)
        assert "non-code matches omitted" not in output
        assert output.count("x =") == 10

    def test_multiple_files_ordered(self) -> None:
        results = [
            {"file": "a.py", "line": 10, "content": "match_a"},
            {"file": "b.py", "line": 20, "content": "match_b"},
        ]
        output = format_grep_results(results, "match", 5, 100)
        assert "a.py:10: match_a" in output
        assert "b.py:20: match_b" in output
        a_pos = output.index("a.py:10")
        b_pos = output.index("b.py:20")
        assert a_pos < b_pos


class TestFlatContextSeparator:
    """Flat (non-densified) context separators and context line formatting."""

    def test_flat_context_separator(self) -> None:
        results = [
            {"file": "a.py", "line": 10, "content": "match1", "type": "match"},
            {"file": "a.py", "line": 50, "content": "match2", "type": "match"},
        ]
        output = format_grep_results(results, "match", 50, 200, is_regex=False)
        lines = output.split("\n")
        assert "--" in lines
        assert "  --" not in lines

    def test_flat_context_line_uses_dash_sep(self) -> None:
        results = [
            {"file": "a.py", "line": 10, "content": "match line", "type": "match"},
            {"file": "a.py", "line": 11, "content": "context line", "type": "context"},
        ]
        output = format_grep_results(results, "match", 50, 200, is_regex=False)
        assert "a.py-11- context line" in output
        assert "a.py:10: match line" in output


class TestCompactMatchLineEdgeCases:
    """Cover remaining branches: omitted_before only, omitted_after only, snippet fallback."""

    def test_omitted_before_only(self) -> None:
        """Match near end of long line — only prefix truncated."""
        line = "a" * 400 + "TARGET"
        result = compact_match_line(line, "TARGET", is_regex=False)
        assert "TARGET" in result
        assert "before" in result
        assert "after" not in result

    def test_omitted_after_only(self) -> None:
        """Match near start of long line — only suffix truncated."""
        line = "TARGET" + "b" * 400
        result = compact_match_line(line, "TARGET", is_regex=False)
        assert "TARGET" in result
        assert "after" in result

    def test_snippet_no_truncation_exactly_max(self) -> None:
        """When the window exactly covers MAX_LINE_CHARS, no truncation marker."""
        line = "x" * MAX_LINE_CHARS
        result = compact_match_line(line, "x", is_regex=False)
        assert result == line
        assert "truncated" not in result


class TestDensification:
    """Path-grouped densification: eliminates repeated paths when >= 5 matches."""

    def test_below_threshold_flat(self) -> None:
        results = [
            {"file": "a.py", "line": i * 10, "content": f"line {i}", "type": "match"}
            for i in range(_DENSIFY_MIN_MATCHES - 1)
        ]
        output = format_grep_results(results, "line", 50, 200, is_regex=False)
        assert "a.py:" in output

    def test_at_threshold_densified(self) -> None:
        results = [
            {"file": "src/long/path/module.py", "line": i * 10, "content": f"match {i}", "type": "match"}
            for i in range(_DENSIFY_MIN_MATCHES)
        ]
        output = format_grep_results(results, "match", 50, 200, is_regex=False)
        lines = output.split("\n")
        assert "src/long/path/module.py" in lines
        indented = [ln for ln in lines if ln.startswith("  ") and "match" in ln]
        assert len(indented) == _DENSIFY_MIN_MATCHES

    def test_single_file_densified(self) -> None:
        results = [
            {"file": "src/utils/api.ts", "line": i * 5, "content": f"data = fetch({i})", "type": "match"}
            for i in range(7)
        ]
        output = format_grep_results(results, "data", 50, 200, is_regex=False)
        lines = output.split("\n")
        path_header_count = sum(1 for ln in lines if ln == "src/utils/api.ts")
        assert path_header_count == 1

    def test_multi_file_densified(self) -> None:
        results = []
        for j, path in enumerate(["a.py", "b.py", "c.py"]):
            for i in range(3):
                results.append({"file": path, "line": 10 + i + j * 100, "content": f"x = {i}", "type": "match"})
        output = format_grep_results(results, "x", 50, 200, is_regex=False)
        lines = output.split("\n")
        assert "a.py" in lines
        assert "b.py" in lines
        assert "c.py" in lines
        assert not any(ln.startswith("a.py:") for ln in lines)

    def test_densified_saves_tokens(self) -> None:
        results = [
            {"file": "src/features/dashboard/UserStatsCard.tsx", "line": i * 10, "content": f"const x = {i};", "type": "match"}
            for i in range(8)
        ]
        dense_output = format_grep_results(results, "x", 50, 200, is_regex=False)
        flat_lines = [
            f"src/features/dashboard/UserStatsCard.tsx:{i * 10}: const x = {i};"
            for i in range(8)
        ]
        flat_total_path_chars = sum(len("src/features/dashboard/UserStatsCard.tsx") for _ in range(8))
        dense_path_chars = len("src/features/dashboard/UserStatsCard.tsx")
        assert dense_path_chars < flat_total_path_chars
        assert len(dense_output) < sum(len(ln) for ln in flat_lines) + 200

    def test_densified_context_separator(self) -> None:
        results = [
            {"file": "a.py", "line": 10, "content": "line1", "type": "match"},
            {"file": "a.py", "line": 50, "content": "line2", "type": "match"},
            {"file": "b.py", "line": 5, "content": "line3", "type": "match"},
            {"file": "b.py", "line": 6, "content": "line4", "type": "match"},
            {"file": "b.py", "line": 100, "content": "line5", "type": "match"},
        ]
        output = format_grep_results(results, "line", 50, 200, is_regex=False)
        assert "  --" in output

    def test_densified_non_code_capping_preserved(self) -> None:
        results = [
            {"file": "data.json", "line": i, "content": f'"key": {i}', "type": "match"}
            for i in range(10)
        ]
        output = format_grep_results(results, "key", 1, 100, is_regex=False)
        assert "non-code matches omitted" in output
        match_lines = [ln for ln in output.split("\n") if ln.strip().startswith(("  ", "data.json")) and "key" in ln and "omitted" not in ln]
        assert len(match_lines) <= NON_CODE_MATCH_CAP + 1

    def test_densified_with_context_lines(self) -> None:
        results = [
            {"file": "a.py", "line": 10, "content": "match line", "type": "match"},
            {"file": "a.py", "line": 11, "content": "context line", "type": "context"},
            {"file": "a.py", "line": 12, "content": "match again", "type": "match"},
            {"file": "b.py", "line": 5, "content": "another", "type": "match"},
            {"file": "b.py", "line": 6, "content": "ctx", "type": "context"},
            {"file": "b.py", "line": 7, "content": "last", "type": "match"},
            {"file": "b.py", "line": 20, "content": "far", "type": "match"},
        ]
        output = format_grep_results(results, "match", 50, 200, is_regex=False)
        lines = output.split("\n")
        context_lines = [ln for ln in lines if "- " in ln and ("context" in ln or "ctx" in ln)]
        assert len(context_lines) >= 1
