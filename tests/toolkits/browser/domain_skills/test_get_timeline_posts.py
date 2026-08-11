"""Unit tests for x-com get_timeline_posts domain tool."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo

_TOOL_PATH = (
    Path(__file__).resolve().parents[4]
    / "src/myrm_agent_harness/toolkits/browser/domain_skills/builtin/x-com/tools/get_timeline_posts.py"
)
_MODULE_NAME = "myrm_agent_harness_x_com_get_timeline_posts"


def _load_get_timeline_posts() -> Any:
    if _MODULE_NAME in sys.modules:
        mod = sys.modules[_MODULE_NAME]
        return mod.get_timeline_posts

    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod.get_timeline_posts


@pytest.mark.asyncio
async def test_extracts_posts_from_article_refs() -> None:
    get_timeline_posts = _load_get_timeline_posts()
    refs = MappingProxyType(
        {
            "e1": RefInfo(role="article", name="Hello from X timeline post", nth=None),
            "e2": RefInfo(role="button", name="Like", nth=None),
        }
    )
    session = MagicMock()
    session.get_all_refs.return_value = refs

    result = await get_timeline_posts(session, {"max_posts": 5})
    posts = json.loads(result)

    assert len(posts) == 1
    assert posts[0]["ref"] == "e1"
    assert "Hello from X timeline" in posts[0]["text"]
    session.snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_triggers_snapshot_when_no_article_refs() -> None:
    get_timeline_posts = _load_get_timeline_posts()
    empty_refs = MappingProxyType({})
    populated_refs = MappingProxyType(
        {
            "e9": RefInfo(role="article", name="Recovered after snapshot refresh", nth=None),
        }
    )
    session = MagicMock()
    session.get_all_refs.side_effect = [empty_refs, populated_refs]
    session.snapshot = AsyncMock(return_value=MagicMock())

    result = await get_timeline_posts(session, {"max_posts": 3})
    posts = json.loads(result)

    session.snapshot.assert_awaited_once()
    assert len(posts) == 1
    assert posts[0]["text"].startswith("Recovered after snapshot")


@pytest.mark.asyncio
async def test_fallback_uses_extract_text_not_get_text_snapshot() -> None:
    get_timeline_posts = _load_get_timeline_posts()
    session = MagicMock()
    session.get_all_refs.return_value = MappingProxyType({})
    session.snapshot = AsyncMock(return_value=MagicMock())
    session.extract_text = AsyncMock(
        return_value="Line one of fallback\n\nLine two of fallback paragraph"
    )

    result = await get_timeline_posts(session, {"max_posts": 2})
    posts = json.loads(result)

    session.extract_text.assert_awaited_once_with(max_length=50000)
    assert len(posts) >= 1
    assert "fallback" in posts[0]["text"]


@pytest.mark.asyncio
async def test_skips_short_article_text_and_respects_max_posts() -> None:
    get_timeline_posts = _load_get_timeline_posts()
    refs = MappingProxyType(
        {
            "e1": RefInfo(role="article", name="short", nth=None),
            "e2": RefInfo(role="article", name="Second valid timeline post text", nth=None),
            "e3": RefInfo(role="article", name="Third valid timeline post text here", nth=None),
        }
    )
    session = MagicMock()
    session.get_all_refs.return_value = refs

    result = await get_timeline_posts(session, {"max_posts": 1})
    posts = json.loads(result)

    assert len(posts) == 1
    assert posts[0]["ref"] == "e2"


@pytest.mark.asyncio
async def test_fallback_flushes_trailing_paragraph() -> None:
    get_timeline_posts = _load_get_timeline_posts()
    session = MagicMock()
    session.get_all_refs.return_value = MappingProxyType({})
    session.snapshot = AsyncMock(return_value=MagicMock())
    session.extract_text = AsyncMock(
        return_value="Only one long trailing paragraph without blank line ending"
    )

    result = await get_timeline_posts(session, {"max_posts": 5})
    posts = json.loads(result)

    assert len(posts) == 1
    assert "trailing paragraph" in posts[0]["text"]


@pytest.mark.asyncio
async def test_fallback_stops_at_max_posts_on_blank_line() -> None:
    get_timeline_posts = _load_get_timeline_posts()
    session = MagicMock()
    session.get_all_refs.return_value = MappingProxyType({})
    session.snapshot = AsyncMock(return_value=MagicMock())
    session.extract_text = AsyncMock(
        return_value=(
            "First paragraph with enough characters here\n\n"
            "Second paragraph with enough characters here\n\n"
            "Third paragraph should not appear"
        )
    )

    result = await get_timeline_posts(session, {"max_posts": 1})
    posts = json.loads(result)

    assert len(posts) == 1
    assert "First paragraph" in posts[0]["text"]
    assert "Second paragraph" not in posts[0]["text"]
