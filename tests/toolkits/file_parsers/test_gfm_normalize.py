"""Tests for shared GFM markdown normalization."""

from __future__ import annotations

from myrm_agent_harness.toolkits.file_parsers.gfm_normalize import (
    normalize_to_gfm_markdown,
)


def test_normalize_to_gfm_markdown_collapses_blank_lines() -> None:
    raw = "Title\n\n\n\nBody   \n"
    assert normalize_to_gfm_markdown(raw) == "Title\n\nBody"
