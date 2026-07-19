"""Tests for aria_parser (Layer 2) - YAML parsing with pyyaml."""

import pytest
import yaml

from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import parse_aria_yaml


class TestAriaParser:
    """Test suite for ARIA YAML parser using pyyaml."""

    def test_parse_simple_tree(self) -> None:
        """Test parsing a simple ARIA tree."""
        yaml_str = """
- WebArea:
    name: "Test Page"
    children:
      - button:
          name: "Submit"
      - link:
          name: "Home"
"""
        nodes = parse_aria_yaml(yaml_str)

        assert len(nodes) == 1
        assert nodes[0].role == "WebArea"
        assert nodes[0].name == "Test Page"
        assert len(nodes[0].children) == 2
        assert nodes[0].children[0].role == "button"
        assert nodes[0].children[0].name == "Submit"
        assert nodes[0].children[1].role == "link"
        assert nodes[0].children[1].name == "Home"

    def test_parse_empty_input(self) -> None:
        """Test parsing empty YAML."""
        assert parse_aria_yaml("") == []
        assert parse_aria_yaml("   ") == []

    def test_parse_scalar_document_role(self) -> None:
        """Bare document scalar from minimal aria_snapshot on empty pages."""
        nodes = parse_aria_yaml("document")
        assert len(nodes) == 1
        assert nodes[0].role == "document"
        assert nodes[0].name == ""

    def test_parse_nested_tree(self) -> None:
        """Test parsing deeply nested tree."""
        yaml_str = """
- WebArea:
    children:
      - navigation:
          children:
            - list:
                children:
                  - listitem:
                      name: "Item 1"
"""
        nodes = parse_aria_yaml(yaml_str)

        assert len(nodes) == 1
        nav = nodes[0].children[0]
        assert nav.role == "navigation"
        lst = nav.children[0]
        assert lst.role == "list"
        item = lst.children[0]
        assert item.role == "listitem"
        assert item.name == "Item 1"

    def test_parse_with_attributes(self) -> None:
        """Test parsing elements with ARIA attributes."""
        yaml_str = """
- button:
    name: "Click me"
    pressed: "true"
    disabled: "false"
"""
        nodes = parse_aria_yaml(yaml_str)

        assert len(nodes) == 1
        assert nodes[0].attributes["pressed"] == "true"
        assert nodes[0].attributes["disabled"] == "false"

    def test_parse_unicode_names(self) -> None:
        """Test parsing Unicode characters in names."""
        yaml_str = """
- button:
    name: "提交按钮 "
"""
        nodes = parse_aria_yaml(yaml_str)

        assert len(nodes) == 1
        assert nodes[0].name == "提交按钮 "

    def test_parse_escaped_quotes(self) -> None:
        """Test parsing escaped quotes in names (pyyaml advantage)."""
        yaml_str = """
- button:
    name: 'He said "hello"'
"""
        nodes = parse_aria_yaml(yaml_str)

        assert len(nodes) == 1
        assert nodes[0].name == 'He said "hello"'

    def test_parse_multiline_names(self) -> None:
        """Test parsing multiline strings (pyyaml advantage)."""
        yaml_str = """
- region:
    name: |
      Line 1
      Line 2
      Line 3
"""
        nodes = parse_aria_yaml(yaml_str)

        assert len(nodes) == 1
        assert "Line 1" in nodes[0].name
        assert "Line 2" in nodes[0].name

    def test_parse_invalid_yaml(self) -> None:
        """Test error handling for invalid YAML."""
        invalid_yaml = "- button: [unclosed"

        with pytest.raises(yaml.YAMLError):
            parse_aria_yaml(invalid_yaml)

    def test_indent_tracking(self) -> None:
        """Test that indent levels are correctly tracked."""
        yaml_str = """
- WebArea:
    children:
      - navigation:
          children:
            - button:
                name: "Test"
"""
        nodes = parse_aria_yaml(yaml_str)

        assert nodes[0].indent == 0  # WebArea
        assert nodes[0].children[0].indent == 1  # navigation
        assert nodes[0].children[0].children[0].indent == 2  # button
