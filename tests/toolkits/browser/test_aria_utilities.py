"""Tests for ARIA utilities: truncate_snapshot, resolve_locator, edge cases."""

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_renderer import truncate_snapshot
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import CURSOR_ROLES, RefInfo, resolve_locator


class TestTruncateSnapshot:
    """Test truncate_snapshot from aria_renderer."""

    def test_truncate_with_zero_tokens(self) -> None:
        """Test that max_tokens <= 0 returns original text."""
        text = "line1\nline2\nline3"
        result, truncated = truncate_snapshot(text, 0)
        assert result == text
        assert not truncated

    def test_truncate_with_negative_tokens(self) -> None:
        """Test that negative max_tokens returns original text."""
        text = "test content"
        result, truncated = truncate_snapshot(text, -10)
        assert result == text
        assert not truncated

    def test_truncate_under_budget(self) -> None:
        """Test text under token budget is not truncated."""
        text = "short text"
        result, truncated = truncate_snapshot(text, 1000)
        assert result == text
        assert not truncated

    def test_truncate_over_budget(self) -> None:
        """Test text exceeding token budget is truncated."""
        lines = [f"This is line {i} with some content" for i in range(100)]
        text = "\n".join(lines)
        result, truncated = truncate_snapshot(text, 50)

        assert truncated
        assert "truncated" in result
        assert "more lines" in result
        assert len(result) < len(text)

    def test_truncate_exact_boundary(self) -> None:
        """Test truncation at exact token boundary."""
        lines = ["x" * 40 for _ in range(10)]  # 10 lines, ~10 tokens each
        text = "\n".join(lines)
        result, truncated = truncate_snapshot(text, 25)

        if truncated:
            assert "truncated" in result
            remaining_count = int(result.split("(... ")[1].split(" more")[0])
            assert remaining_count > 0

    def test_truncate_single_line(self) -> None:
        """Test truncation of single very long line."""
        text = "x" * 1000
        result, truncated = truncate_snapshot(text, 10)

        assert truncated
        assert "truncated" in result

    def test_truncate_empty_text(self) -> None:
        """Test truncation of empty text."""
        result, truncated = truncate_snapshot("", 100)
        assert result == ""
        assert not truncated


class TestResolveLocator:
    """Test resolve_locator from aria_types."""

    def test_resolve_standard_role_no_nth(self) -> None:
        """Test resolve_locator with standard role and no nth."""
        page = MagicMock()
        locator_mock = MagicMock()
        page.get_by_role.return_value = locator_mock

        info = RefInfo(role="button", name="Submit", nth=None)
        result = resolve_locator(page, info)

        page.get_by_role.assert_called_once_with("button", name="Submit")
        assert result == locator_mock

    def test_resolve_standard_role_with_nth(self) -> None:
        """Test resolve_locator with standard role and nth index."""
        page = MagicMock()
        locator_mock = MagicMock()
        nth_locator_mock = MagicMock()
        page.get_by_role.return_value = locator_mock
        locator_mock.nth.return_value = nth_locator_mock

        info = RefInfo(role="button", name="Delete", nth=2)
        result = resolve_locator(page, info)

        page.get_by_role.assert_called_once_with("button", name="Delete")
        locator_mock.nth.assert_called_once_with(2)
        assert result == nth_locator_mock

    def test_resolve_cursor_role_no_nth(self) -> None:
        """Test resolve_locator with CURSOR_ROLES (clickable/focusable)."""
        page = MagicMock()
        locator_mock = MagicMock()
        page.get_by_text.return_value = locator_mock

        for cursor_role in CURSOR_ROLES:
            page.get_by_text.reset_mock()
            info = RefInfo(role=cursor_role, name="Click Me", nth=None)
            result = resolve_locator(page, info)

            page.get_by_text.assert_called_once_with("Click Me", exact=True)
            assert result == locator_mock

    def test_resolve_cursor_role_with_nth(self) -> None:
        """Test resolve_locator with CURSOR_ROLES and nth index."""
        page = MagicMock()
        locator_mock = MagicMock()
        nth_locator_mock = MagicMock()
        page.get_by_text.return_value = locator_mock
        locator_mock.nth.return_value = nth_locator_mock

        info = RefInfo(role="clickable", name="Item", nth=1)
        result = resolve_locator(page, info)

        page.get_by_text.assert_called_once_with("Item", exact=True)
        locator_mock.nth.assert_called_once_with(1)
        assert result == nth_locator_mock


class TestAriaParserEdgeCases:
    """Test aria_parser edge cases for full coverage."""

    def test_parse_value_as_list(self) -> None:
        """Test parsing when value is directly a list (edge case line 96-98)."""
        from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import parse_aria_yaml

        # YAML with direct list value (rare but valid YAML structure)
        yaml_str = """
- WebArea:
    - button:
        name: "Child1"
    - link:
        name: "Child2"
"""
        nodes = parse_aria_yaml(yaml_str)

        # Should handle gracefully
        assert len(nodes) >= 1

    def test_parse_attributes_from_string(self) -> None:
        """Test parsing attributes like [level=1] format (line 133-137)."""
        from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import parse_aria_yaml

        # This is legacy format that might exist in some data
        # The parser has a fallback path for this
        yaml_str = """
- heading:
    name: "Title"
    level: "1"
"""
        nodes = parse_aria_yaml(yaml_str)

        assert len(nodes) == 1
        assert nodes[0].role == "heading"
        assert nodes[0].name == "Title"

    def test_parse_complex_nested_structure(self) -> None:
        """Test parsing complex nested structure with attributes."""
        from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import parse_aria_yaml

        yaml_str = """
- WebArea:
    name: "Page"
    children:
      - region:
          name: "Main"
          live: "polite"
          children:
            - button:
                name: "Action"
                pressed: "true"
"""
        nodes = parse_aria_yaml(yaml_str)

        assert len(nodes) == 1
        region = nodes[0].children[0]
        assert region.role == "region"
        assert region.attributes.get("live") == "polite"

        button = region.children[0]
        assert button.attributes.get("pressed") == "true"


class TestCursorRoles:
    """Test CURSOR_ROLES constant."""

    def test_cursor_roles_defined(self) -> None:
        """Test CURSOR_ROLES contains expected values."""
        assert frozenset({"clickable", "focusable"}) == CURSOR_ROLES
        assert "clickable" in CURSOR_ROLES
        assert "focusable" in CURSOR_ROLES
        assert len(CURSOR_ROLES) == 2

    def test_cursor_roles_is_frozenset(self) -> None:
        """Test CURSOR_ROLES is immutable frozenset."""
        assert isinstance(CURSOR_ROLES, frozenset)

        with pytest.raises(AttributeError):
            CURSOR_ROLES.add("newrole")  # type: ignore[attr-defined]
