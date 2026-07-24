"""Tests for web fetch markdown sanitization."""

from myrm_agent_harness.toolkits.web_fetch.content_sanitize import (
    strip_base64_images_from_markdown,
)


def test_strip_base64_markdown_image() -> None:
    blob = "A" * 200
    md = f"![chart](data:image/png;base64,{blob})"
    out = strip_base64_images_from_markdown(md)
    assert "[IMAGE: chart]" in out
    assert "base64" not in out
