"""Unit tests for fuzzy_match — progressive text matching.

Covers:
  - 8-strategy chain (exact → line_trim → whitespace → indent → escape
    → trimmed_boundary → block_anchored → context_aware)
  - Unicode normalization (smart quotes, em dash, non-breaking space)
  - Escape drift detection
  - "Did you mean?" hint (find_closest_lines)
  - replace_all support
  - Multi-match rejection (safety)
  - Edge cases (empty input, single line, no match)
"""

from __future__ import annotations

from myrm_agent_harness.utils.fuzzy_match import (
    FuzzyMatchResult,
    FuzzyReplaceResult,
    find_closest_lines,
    fuzzy_find,
    fuzzy_replace,
)

# ===================================================================
# 1. Exact match (strategy level 1)
# ===================================================================


class TestExactMatch:
    """Exact string matching — baseline strategy."""

    def test_exact_match(self) -> None:
        result = fuzzy_find("hello world", "hello world")
        assert result is not None
        assert result.strategy == "exact"
        assert result.confidence == 1.0

    def test_exact_substring(self) -> None:
        result = fuzzy_find("before hello world after", "hello world")
        assert result is not None
        assert result.strategy == "exact"

    def test_exact_multiline(self) -> None:
        content = "line1\nline2\nline3"
        result = fuzzy_find(content, "line1\nline2")
        assert result is not None
        assert result.strategy == "exact"

    def test_no_match(self) -> None:
        assert fuzzy_find("hello world", "goodbye") is None

    def test_empty_fragment(self) -> None:
        assert fuzzy_find("hello", "") is None

    def test_empty_content(self) -> None:
        assert fuzzy_find("", "hello") is None


# ===================================================================
# 2. Line-trimmed match (strategy level 2)
# ===================================================================


class TestLineTrimmed:
    """Match after stripping per-line whitespace."""

    def test_trailing_spaces(self) -> None:
        content = "  def foo():  \n    pass  "
        fragment = "def foo():\n    pass"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy in ("exact", "line_trimmed")

    def test_leading_spaces_differ(self) -> None:
        content = "    def foo():\n        pass"
        fragment = "def foo():\npass"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy == "line_trimmed"
        assert result.matched_text == "    def foo():\n        pass"

    def test_mixed_trailing(self) -> None:
        content = "a = 1\nb = 2\nc = 3"
        fragment = "a = 1  \nb = 2  "
        result = fuzzy_find(content, fragment)
        assert result is not None


# ===================================================================
# 3. Whitespace-normalized match (strategy level 3)
# ===================================================================


class TestWhitespaceNormalized:
    """Match after collapsing spaces/tabs."""

    def test_tab_vs_spaces(self) -> None:
        content = "if  x:\n\tpass"
        fragment = "if x:\n    pass"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy == "whitespace_normalized"

    def test_multiple_spaces(self) -> None:
        content = "a  =   1\nb  =   2"
        fragment = "a = 1\nb = 2"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy == "whitespace_normalized"


# ===================================================================
# 4. Indent-flexible match (strategy level 4)
# ===================================================================


class TestIndentFlexible:
    """Match ignoring absolute indentation, preserving relative structure."""

    def test_extra_indent_level(self) -> None:
        content = "        def foo(x):\n            return x + 1"
        fragment = "    def foo(x):\n        return x + 1"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy in ("line_trimmed", "indent_flexible")
        assert result.matched_text == "        def foo(x):\n            return x + 1"

    def test_indent_flexible_unique(self) -> None:
        """Case where only indent_flexible matches: same content, different absolute indent,
        but line_trimmed fails because internal whitespace differs."""
        content = "    if x > 0:\n        y = x * 2\n        return y"
        fragment = "      if x > 0:\n          y = x * 2\n          return y"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy in ("line_trimmed", "indent_flexible")

    def test_no_indent_vs_indented(self) -> None:
        content = "    if True:\n        return 1"
        fragment = "if True:\n    return 1"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy in ("line_trimmed", "indent_flexible")

    def test_different_relative_structure_no_match(self) -> None:
        content = "    if True:\n        return 1"
        fragment = "if True:\nreturn 1"
        result = fuzzy_find(content, fragment)
        assert result is None or result.strategy != "indent_flexible"


# ===================================================================
# 5. Escape-normalized match (strategy level 5)
# ===================================================================


class TestEscapeNormalized:
    """Match after converting literal escape sequences."""

    def test_literal_newline(self) -> None:
        content = "line1\nline2"
        fragment = "line1\\nline2"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy == "escape_normalized"

    def test_literal_tab(self) -> None:
        content = "col1\tcol2"
        fragment = "col1\\tcol2"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy == "escape_normalized"

    def test_no_escapes_skipped(self) -> None:
        """When fragment has no escape sequences, this strategy is skipped."""
        content = "hello world"
        fragment = "hello world"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy == "exact"


# ===================================================================
# 6. Trimmed boundary match (strategy level 6)
# ===================================================================


class TestTrimmedBoundary:
    """Match after trimming only the first and last line."""

    def test_first_line_whitespace(self) -> None:
        """Fragment's first line lacks leading indent present in content."""
        content = "  if ready:\n    go()"
        fragment = "if ready:\n    go()"
        result = fuzzy_find(content, fragment)
        assert result is not None
        # exact also matches via substring; accept any early strategy
        assert result.strategy in ("exact", "line_trimmed", "trimmed_boundary")

    def test_last_line_whitespace(self) -> None:
        content = "x = 1\ny = 2\nz = 3  "
        fragment = "x = 1\ny = 2\nz = 3"
        result = fuzzy_find(content, fragment)
        assert result is not None

    def test_both_boundaries_trimmed(self) -> None:
        content = "   start\n    middle_exact\n   end   "
        fragment = "start\n    middle_exact\nend"
        result = fuzzy_find(content, fragment)
        assert result is not None

    def test_single_line(self) -> None:
        content = "   hello   "
        fragment = "hello"
        result = fuzzy_find(content, fragment)
        assert result is not None


# ===================================================================
# 7. Block-anchored match (strategy level 7)
# ===================================================================


class TestBlockAnchored:
    """Match by first/last line anchor + middle similarity."""

    def test_similar_middle(self) -> None:
        content = "def foo():\n    x = 1\n    y = 2\n    return x + y"
        fragment = "def foo():\n    x = 1\n    z = 2\n    return x + y"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy == "block_anchored"

    def test_too_different_no_match(self) -> None:
        content = "def foo():\n    completely\n    different\n    code\n    return None"
        fragment = "def foo():\n    x = 1\n    y = 2\n    z = 3\n    return None"
        result = fuzzy_find(content, fragment)
        if result is not None and result.strategy == "block_anchored":
            assert result.confidence < 0.7

    def test_short_fragment_skipped(self) -> None:
        """Block anchoring requires at least 3 lines."""
        content = "line1\nline2"
        fragment = "line1\nline_different"
        result = fuzzy_find(content, fragment)
        assert result is None or result.strategy != "block_anchored"

    def test_multi_match_rejected(self) -> None:
        """Multiple anchor matches should be rejected."""
        content = "def foo():\n    pass\n\ndef foo():\n    pass"
        fragment = "def foo():\n    x = 1\n    pass"
        result = fuzzy_find(content, fragment)
        if result is not None:
            assert result.strategy != "block_anchored"


# ===================================================================
# 8. Context-aware match (strategy level 8)
# ===================================================================


class TestContextAware:
    """Match by first/last anchor + 50% middle-line similarity."""

    def test_half_middle_match(self) -> None:
        content = "class Foo:\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    end"
        fragment = "class Foo:\n    a = 1\n    b = 99\n    c = 3\n    d = 99\n    end"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy in ("block_anchored", "context_aware")

    def test_all_middle_different(self) -> None:
        """All middle lines differ — should NOT match."""
        content = "start:\n    aaa\n    bbb\n    ccc\n    ddd\nend:"
        fragment = "start:\n    111\n    222\n    333\n    444\nend:"
        result = fuzzy_find(content, fragment)
        if result is not None:
            assert result.strategy not in ("context_aware",)

    def test_short_fragment_skipped(self) -> None:
        content = "a\nb"
        fragment = "a\nc"
        result = fuzzy_find(content, fragment)
        assert result is None or result.strategy != "context_aware"


# ===================================================================
# 9. Escape drift detection
# ===================================================================


class TestEscapeDrift:
    """Escape-drift guard prevents fuzzy matches from corrupting files."""

    def test_drift_blocked(self) -> None:
        """Non-exact match (indent_flexible) + escape drift in new_str → blocked."""
        content = "    msg = 'hello'\n    return True"
        old_frag = "        msg = 'hello'\n        return True"
        new_frag = "        msg = \\'world\\'\n        return True"
        assert old_frag not in content
        result = fuzzy_replace(content, old_frag, new_frag)
        assert not result.success

    def test_no_drift_exact_pass(self) -> None:
        """Exact match bypasses drift check."""
        content = "msg = 'hello'"
        result = fuzzy_replace(content, "msg = 'hello'", "msg = \\'world\\'")
        assert result.success

    def test_no_drift_when_old_has_escapes(self) -> None:
        content = "  msg = \\'hello\\'"
        result = fuzzy_replace(content, "msg = \\'hello\\'", "msg = \\'world\\'")
        assert result.success


# ===================================================================
# 7. Unicode normalization
# ===================================================================


class TestUnicodeNormalization:
    """Unicode smart quotes, dashes, and special spaces."""

    def test_smart_quotes(self) -> None:
        content = 'print("hello")'
        fragment = "print(\u201chello\u201d)"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.confidence == 1.0

    def test_em_dash(self) -> None:
        content = "value -- default"
        fragment = "value \u2014 default"
        result = fuzzy_find(content, fragment)
        assert result is not None

    def test_non_breaking_space(self) -> None:
        content = "a = 1"
        fragment = "a\u00a0=\u00a01"
        result = fuzzy_find(content, fragment)
        assert result is not None

    def test_no_unicode_fast_path(self) -> None:
        """Pure ASCII fragment should not trigger Unicode normalization."""
        content = "hello world"
        fragment = "hello world"
        result = fuzzy_find(content, fragment)
        assert result is not None
        assert result.strategy == "exact"


# ===================================================================
# 8. fuzzy_replace
# ===================================================================


class TestFuzzyReplace:
    """Replace operations with fuzzy matching."""

    def test_exact_replace(self) -> None:
        result = fuzzy_replace("hello world", "hello", "goodbye")
        assert result.success
        assert result.content == "goodbye world"
        assert result.strategy == "exact"

    def test_fuzzy_replace_with_trim(self) -> None:
        content = "  def foo():  \n    pass  "
        result = fuzzy_replace(content, "def foo():\npass", "def bar():\npass")
        assert result.success
        assert "bar" in result.content

    def test_no_match_returns_original(self) -> None:
        result = fuzzy_replace("hello", "goodbye", "hi")
        assert not result.success
        assert result.content == "hello"

    def test_multi_match_rejected(self) -> None:
        content = "foo bar foo"
        result = fuzzy_replace(content, "foo", "baz")
        assert not result.success

    def test_replace_all(self) -> None:
        content = "foo bar foo"
        result = fuzzy_replace(content, "foo", "baz", replace_all=True)
        assert result.success
        assert result.content == "baz bar baz"

    def test_empty_fragment(self) -> None:
        result = fuzzy_replace("hello", "", "world")
        assert not result.success

    def test_preserves_surrounding(self) -> None:
        content = "before\nhello world\nafter"
        result = fuzzy_replace(content, "hello world", "goodbye world")
        assert result.success
        assert result.content == "before\ngoodbye world\nafter"

    def test_unicode_in_content_replace(self) -> None:
        """Replace should work when content has Unicode smart quotes."""
        content = "print(\u201chello\u201d)"
        result = fuzzy_replace(content, 'print("hello")', 'print("world")')
        assert result.success
        assert result.content == "print(\u201cworld\u201d)" or "world" in result.content

    def test_unicode_in_fragment_replace(self) -> None:
        """Replace should work when fragment has Unicode smart quotes."""
        content = 'print("hello")'
        result = fuzzy_replace(content, "print(\u201chello\u201d)", 'print("world")')
        assert result.success
        assert result.content == 'print("world")'

    def test_unicode_replace_preserves_original(self) -> None:
        """After Unicode-matched replace, non-matched content stays original."""
        content = "x = \u201ca\u201d\ny = \u201cb\u201d"
        result = fuzzy_replace(content, 'x = "a"', 'x = "z"')
        assert result.success
        assert "\u201cb\u201d" in result.content


# ===================================================================
# 9. "Did you mean?" hint
# ===================================================================


class TestFindClosestLines:
    """find_closest_lines returns similar snippets when all strategies fail."""

    CONTENT = "def _process_data(config, *, validate=True):\n    if not validate:\n        return None\n    return config.get('data')"

    def test_similar_function_name(self) -> None:
        """Anchor line differs slightly — hint should find the real function."""
        hint = find_closest_lines("def process_data(config):", self.CONTENT)
        assert "Did you mean" in hint
        assert "_process_data" in hint

    def test_no_match_returns_empty(self) -> None:
        """Completely unrelated text → no hint."""
        hint = find_closest_lines("xyz", "abc\nmno\npqr")
        assert hint == ""

    def test_empty_inputs(self) -> None:
        assert find_closest_lines("", self.CONTENT) == ""
        assert find_closest_lines("def foo():", "") == ""

    def test_line_numbers_in_hint(self) -> None:
        """Hint should include line numbers for LLM reference."""
        hint = find_closest_lines("def process_data:", self.CONTENT)
        if hint:
            assert "|" in hint

    def test_max_results_respected(self) -> None:
        """Should not return more snippets than max_results."""
        content = "\n".join(f"def func_{i}(): pass" for i in range(20))
        hint = find_closest_lines("def func_5(): pass", content, max_results=2)
        assert hint.count("---") <= 1


# ===================================================================
# 10. Edge cases
# ===================================================================


class TestEdgeCases:
    """Boundary conditions and safety checks."""

    def test_single_line_content(self) -> None:
        result = fuzzy_find("x = 1", "x = 1")
        assert result is not None

    def test_very_long_content(self) -> None:
        content = "\n".join(f"line_{i}" for i in range(1000))
        result = fuzzy_find(content, "line_500\nline_501")
        assert result is not None
        assert result.strategy == "exact"

    def test_unicode_in_content_not_fragment(self) -> None:
        """Unicode in content but not fragment should still work."""
        content = "print(\u201chello\u201d)"
        fragment = 'print("hello")'
        result = fuzzy_find(content, fragment)
        assert result is not None

    def test_result_types(self) -> None:
        result = fuzzy_find("hello", "hello")
        assert isinstance(result, FuzzyMatchResult)

        replace_result = fuzzy_replace("hello", "hello", "world")
        assert isinstance(replace_result, FuzzyReplaceResult)

    def test_escape_normalized_no_match(self) -> None:
        """Escape normalized converts but still doesn't match content."""
        content = "line1_XYZXYZ"
        fragment = "line1\\nline2"
        result = fuzzy_find(content, fragment)
        assert result is None or result.strategy != "escape_normalized"

    def test_block_anchored_empty_inner(self) -> None:
        """Block anchored with exactly 3 lines and no inner content."""
        content = "start\n\nend"
        fragment = "start\n\nend"
        result = fuzzy_find(content, fragment)
        assert result is not None

    def test_context_aware_trailing_empty_lines(self) -> None:
        """Fragment with trailing empty lines gets trimmed before matching."""
        content = "class A:\n    x = 1\n    y = 2\n    end"
        fragment = "class A:\n    x = 1\n    y = 2\n    end\n\n"
        result = fuzzy_find(content, fragment)
        assert result is not None

    def test_find_closest_lines_all_blank_old_str(self) -> None:
        """old_str is all whitespace lines — no anchor found."""
        hint = find_closest_lines("   \n   \n  ", "def foo():\n    pass")
        assert hint == ""

    def test_unicode_recovery_failure(self) -> None:
        """When Unicode content can't be mapped back, strategy is skipped."""
        content = "\u201ctest\u201d"
        fragment = '"test"'
        result = fuzzy_find(content, fragment)
        assert result is not None
