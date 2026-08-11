"""Tests for markdown frontmatter helpers."""

from __future__ import annotations

from myrm_agent_harness.utils.markdown_frontmatter import (
    has_frontmatter_block,
    parse_frontmatter,
    preserve_frontmatter_on_edit,
)


def test_parse_frontmatter_inline_tags() -> None:
    content = "---\ntags: [python, web]\n---\n# Hello\n"
    meta, body = parse_frontmatter(content)
    assert meta["tags"] == ["python", "web"]
    assert body.startswith("# Hello")


def test_preserve_frontmatter_on_edit_reinjects_block() -> None:
    pre = "---\ndate: 2026-07-28\ntags: [daily]\n---\n# Title\n\nOld body\n"
    post = "# Title\n\nNew body\n"
    merged, warnings = preserve_frontmatter_on_edit(pre, post)
    assert has_frontmatter_block(merged)
    assert "date: 2026-07-28" in merged
    assert "New body" in merged
    assert warnings


def test_preserve_frontmatter_on_edit_keeps_explicit_frontmatter() -> None:
    pre = "---\ndate: old\n---\n# Title\n"
    post = "---\ndate: new\n---\n# Title\n"
    merged, warnings = preserve_frontmatter_on_edit(pre, post)
    assert merged == post
    assert not warnings
