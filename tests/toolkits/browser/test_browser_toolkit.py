"""Tests for myrm_agent_harness.toolkits.browser — snapshot parsing and role classification.

This file focuses on core P0 functionality:
- P0-A2: Three-tier role classification (INTERACTIVE / CONTENT / STRUCTURAL)
- Scope parameter (interactive / content / full)
- Compact format optimization
- truncate_snapshot utility

Integration tests for cursor-interactive detection and semantic diff are in:
- tests/toolkits/browser/test_cursor_interactive_integration.py
- tests/toolkits/browser/test_semantic_diff_comprehensive.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.snapshot import RefInfo, truncate_snapshot
from myrm_agent_harness.toolkits.browser.snapshot.aria_enhancer import enhance_aria_tree
from myrm_agent_harness.toolkits.browser.snapshot.aria_parser import parse_aria_yaml
from myrm_agent_harness.toolkits.browser.snapshot.aria_renderer import render_to_yaml
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import SnapshotMeta


def _parse_and_enhance_wrapper(
    aria_tree: str,
    *,
    scope: str = "interactive",
    compact: bool = False,
    bbox_map: dict[str, dict[str, int | dict[str, int]]] | None = None,
) -> tuple[str, dict[str, RefInfo], SnapshotMeta]:
    """Test helper: wraps four-layer architecture to match old API signature."""
    nodes = parse_aria_yaml(aria_tree)
    enhanced_nodes, refs = enhance_aria_tree(nodes, scope=scope, compact=compact, bbox_map=bbox_map)
    text, meta = render_to_yaml(enhanced_nodes, compact=compact)
    return text, refs, meta


def _tree_to_yaml(tree: dict[str, object], indent: int = 0) -> str:
    """Convert dict-based ARIA tree to standard YAML format (Playwright aria_snapshot format)."""
    role = str(tree.get("role", "generic"))
    name = str(tree.get("name", ""))
    children = tree.get("children") or []

    prefix = "  " * indent
    lines = [f"{prefix}- {role}:"]

    if name:
        lines.append(f"{prefix}    name: {name!r}")

    if children:
        lines.append(f"{prefix}    children:")
        for child in children:
            if isinstance(child, dict):
                child_lines = _tree_to_yaml(child, indent + 2).split("\n")
                lines.extend(child_lines)

    return "\n".join(lines)


_SIMPLE_TREE: dict[str, object] = {
    "role": "WebArea",
    "name": "Test Page",
    "children": [
        {"role": "link", "name": "Home"},
        {"role": "textbox", "name": "Search"},
        {"role": "button", "name": "Go"},
    ],
}


# ============================================================================
# parse_and_enhance_aria_tree — basic parsing
# ============================================================================


def test_parse_and_enhance_aria_tree_interactive_scope():
    yaml_tree = _tree_to_yaml(_SIMPLE_TREE)
    text, refs, meta = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert len(refs) == 3
    assert refs["e0"] == RefInfo("link", "Home", None)
    assert refs["e1"] == RefInfo("textbox", "Search", None)
    assert refs["e2"] == RefInfo("button", "Go", None)
    assert "[ref=e0]" in text or "e0" in text
    assert 'WebArea "Test Page"' in text
    assert meta.ref_count == 3
    assert meta.estimated_tokens > 0


def test_parse_and_enhance_aria_tree_full_scope():
    yaml_tree = _tree_to_yaml(_SIMPLE_TREE)
    _text, refs, meta = _parse_and_enhance_wrapper(yaml_tree, scope="full")
    assert len(refs) == 4
    assert refs["e0"] == RefInfo("WebArea", "Test Page", None)
    assert meta.ref_count == 4


def test_parse_and_enhance_aria_tree_nested():
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "",
        "children": [
            {
                "role": "navigation",
                "name": "Nav",
                "children": [
                    {"role": "link", "name": "Page 1"},
                    {"role": "link", "name": "Page 2"},
                ],
            },
            {
                "role": "main",
                "name": "",
                "children": [
                    {"role": "textbox", "name": "Email"},
                    {"role": "button", "name": "Login"},
                ],
            },
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    _, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert len(refs) == 4
    assert refs["e0"].name == "Page 1"
    assert refs["e3"].name == "Login"


def test_parse_and_enhance_aria_tree_nth_disambiguation():
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "",
        "children": [
            {"role": "button", "name": "Delete"},
            {"role": "button", "name": "Delete"},
            {"role": "button", "name": "Delete"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    _, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert refs["e0"].nth == 0
    assert refs["e1"].nth == 1
    assert refs["e2"].nth == 2


def test_parse_and_enhance_aria_tree_empty_tree():
    yaml_tree = _tree_to_yaml({"role": "WebArea", "name": ""})
    text, refs, meta = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert refs == {}
    assert text == '- WebArea ""' or text == ""
    assert meta.ref_count == 0


def test_parse_and_enhance_aria_tree_no_interactive():
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "Page",
        "children": [{"role": "heading", "name": "Title"}],
    }
    yaml_tree = _tree_to_yaml(tree)
    text, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert refs == {}
    assert 'heading "Title"' in text


_ALL_INTERACTIVE_ROLES = [
    "button",
    "checkbox",
    "combobox",
    "link",
    "listbox",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "radio",
    "searchbox",
    "slider",
    "spinbutton",
    "switch",
    "tab",
    "textbox",
    "treeitem",
]


@pytest.mark.parametrize("role", _ALL_INTERACTIVE_ROLES)
def test_interactive_role_gets_ref(role: str):
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "",
        "children": [{"role": role, "name": "test"}],
    }
    yaml_tree = _tree_to_yaml(tree)
    _, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert len(refs) == 1
    assert refs["e0"].role == role


# ============================================================================
# parse_and_enhance_aria_tree — compact format
# ============================================================================


def test_parse_and_enhance_aria_tree_compact_format():
    yaml_tree = _tree_to_yaml(_SIMPLE_TREE)
    text, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive", compact=True)
    assert len(refs) == 3
    assert "e0:link" in text
    assert "e1:textbox" in text
    assert "e2:button" in text
    assert "  " not in text.split("\n")[0]


def test_parse_and_enhance_aria_tree_compact_non_interactive():
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "Page",
        "children": [
            {"role": "heading", "name": "Title"},
            {"role": "button", "name": "Click"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    text, _, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive", compact=True)
    assert 'heading "Title"' in text
    assert "e0:button" in text


def test_compact_saves_tokens():
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "",
        "children": [
            {
                "role": "navigation",
                "name": "Nav",
                "children": [{"role": "link", "name": f"Link {i}"} for i in range(10)],
            },
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    normal, _, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive", compact=False)
    compact, _, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive", compact=True)
    assert len(compact) < len(normal)


# ============================================================================
# parse_and_enhance_aria_tree — three-tier role classification (P0-A2)
# ============================================================================


def test_content_scope_heading_gets_ref():
    """In content scope, heading elements with names should get refs."""
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "Page",
        "children": [
            {"role": "heading", "name": "Products"},
            {"role": "button", "name": "Buy"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    _text, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="content")
    assert len(refs) == 2
    assert refs["e0"] == RefInfo("heading", "Products", None)
    assert refs["e1"] == RefInfo("button", "Buy", None)


def test_content_scope_cell_gets_ref():
    """In content scope, table cells should get refs."""
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "",
        "children": [
            {"role": "columnheader", "name": "Price"},
            {"role": "cell", "name": "$299"},
            {"role": "button", "name": "Add"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    _text, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="content")
    assert len(refs) == 3
    assert refs["e0"] == RefInfo("columnheader", "Price", None)
    assert refs["e1"] == RefInfo("cell", "$299", None)
    assert refs["e2"] == RefInfo("button", "Add", None)


def test_interactive_scope_heading_no_ref():
    """In interactive scope, heading elements should show as context without ref."""
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "Page",
        "children": [
            {"role": "heading", "name": "Products"},
            {"role": "button", "name": "Buy"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    text, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert len(refs) == 1
    assert refs["e0"] == RefInfo("button", "Buy", None)
    assert 'heading "Products"' in text


def test_interactive_scope_is_default():
    """Default scope should be 'interactive'."""
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "",
        "children": [
            {"role": "heading", "name": "Title"},
            {"role": "link", "name": "Home"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    text_default, refs_default, _ = _parse_and_enhance_wrapper(yaml_tree)
    text_interactive, refs_interactive, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert text_default == text_interactive
    assert refs_default == refs_interactive


def test_full_scope_structural_gets_ref():
    """In full scope, structural elements should get refs."""
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "",
        "children": [
            {"role": "group", "name": "Section"},
            {"role": "button", "name": "Go"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    _, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="full")
    assert len(refs) == 3
    assert refs["e0"] == RefInfo("WebArea", "", None)
    assert refs["e1"] == RefInfo("group", "Section", None)


def test_full_compact_filters_unnamed_structural():
    """In full scope + compact, unnamed structural elements should be filtered."""
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "Page",
        "children": [
            {"role": "generic", "name": ""},
            {"role": "group", "name": ""},
            {"role": "group", "name": "Named Group"},
            {"role": "button", "name": "Click"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    text, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="full", compact=True)
    assert "Named Group" in text or "group" in text
    assert "Click" in text or "button" in text
    assert len(refs) == 3


# ============================================================================
# truncate_snapshot
# ============================================================================


def test_truncate_no_limit():
    text = "line1\nline2\nline3"
    result, truncated = truncate_snapshot(text, 0)
    assert result == text
    assert not truncated


def test_truncate_under_budget():
    text = "hi"
    result, truncated = truncate_snapshot(text, 100)
    assert result == text
    assert not truncated


def test_truncate_over_budget():
    lines = [f'e{i} [button] "Button {i}"' for i in range(100)]
    text = "\n".join(lines)
    result, truncated = truncate_snapshot(text, 50)
    assert truncated
    assert "truncated" in result
    assert "more lines" in result
    assert len(result) < len(text)


def test_truncate_exact_boundary():
    """Test truncation at exact token boundary."""
    text = "a" * 100
    result, truncated = truncate_snapshot(text, 25)
    if truncated:
        assert len(result) < len(text)
    else:
        assert result == text


# ============================================================================
# P0-A7: nth post-processing (unique element optimization)
# ============================================================================


def test_nth_removed_for_unique_elements():
    """Unique elements should have nth=None after post-processing."""
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "",
        "children": [
            {"role": "button", "name": "Unique"},
            {"role": "button", "name": "Duplicate"},
            {"role": "button", "name": "Duplicate"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    _, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert refs["e0"].nth is None
    assert refs["e1"].nth == 0
    assert refs["e2"].nth == 1


def test_nth_preserved_for_duplicates():
    """Duplicate elements should keep their nth indices."""
    tree: dict[str, object] = {
        "role": "WebArea",
        "name": "",
        "children": [
            {"role": "link", "name": "Item"},
            {"role": "link", "name": "Item"},
            {"role": "link", "name": "Item"},
        ],
    }
    yaml_tree = _tree_to_yaml(tree)
    _, refs, _ = _parse_and_enhance_wrapper(yaml_tree, scope="interactive")
    assert all(refs[f"e{i}"].nth == i for i in range(3))


# ============================================================================
# resolve_locator — Locator reconstruction
# ============================================================================


def test_resolve_locator_standard_role():
    """Standard ARIA roles should use get_by_role."""
    from unittest.mock import MagicMock

    page = MagicMock()
    locator_mock = MagicMock()
    page.get_by_role.return_value = locator_mock

    from myrm_agent_harness.toolkits.browser.snapshot import resolve_locator

    info = RefInfo(role="button", name="Submit", nth=None)
    result = resolve_locator(page, info)

    page.get_by_role.assert_called_once_with("button", name="Submit")
    locator_mock.nth.assert_not_called()
    assert result == locator_mock


def test_resolve_locator_with_nth():
    """Elements with nth should call .nth() on the locator."""
    from unittest.mock import MagicMock

    page = MagicMock()
    locator_mock = MagicMock()
    nth_locator_mock = MagicMock()
    page.get_by_role.return_value = locator_mock
    locator_mock.nth.return_value = nth_locator_mock

    from myrm_agent_harness.toolkits.browser.snapshot import resolve_locator

    info = RefInfo(role="button", name="Delete", nth=2)
    result = resolve_locator(page, info)

    page.get_by_role.assert_called_once_with("button", name="Delete")
    locator_mock.nth.assert_called_once_with(2)
    assert result == nth_locator_mock


def test_resolve_locator_cursor_role():
    """Cursor-interactive elements should use get_by_text."""
    from unittest.mock import MagicMock

    page = MagicMock()
    locator_mock = MagicMock()
    page.get_by_text.return_value = locator_mock

    from myrm_agent_harness.toolkits.browser.snapshot import resolve_locator

    info = RefInfo(role="clickable", name="Buy Now", nth=None)
    result = resolve_locator(page, info)

    page.get_by_text.assert_called_once_with("Buy Now", exact=True)
    page.get_by_role.assert_not_called()
    assert result == locator_mock
