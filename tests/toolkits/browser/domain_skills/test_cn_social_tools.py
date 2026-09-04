"""Unit tests for builtin CN social domain skill tools (Bilibili, Xiaohongshu, Douyin)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

_BUILTIN_DIR = (
    Path(__file__).resolve().parents[4]
    / "src/myrm_agent_harness/toolkits/browser/domain_skills/builtin"
)


def _load_tool(skill_id: str, tool_file: str, callable_name: str) -> Callable[..., Any]:
    module_name = f"myrm_agent_harness_domain_{skill_id}_{callable_name}"
    if module_name in sys.modules:
        mod = sys.modules[module_name]
        return getattr(mod, callable_name)

    tool_path = _BUILTIN_DIR / skill_id / "tools" / tool_file
    spec = importlib.util.spec_from_file_location(module_name, tool_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return getattr(mod, callable_name)


class _MockRefInfo:
    def __init__(self, role: str, name: str, url: str = "") -> None:
        self.role = role
        self.name = name
        self.url = url


# ---------------------------------------------------------------------------
# Bilibili: get_feed_videos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bilibili_extracts_videos_from_semantic_refs() -> None:
    get_feed_videos = _load_tool("bilibili", "get_feed_videos.py", "get_feed_videos")

    refs = MappingProxyType(
        {
            "e1": _MockRefInfo(role="link", name="【4K】超燃混剪！全网最强视觉盛宴", url="/video/BV1xx411c7mD"),
            "e2": _MockRefInfo(role="link", name="首页导航", url="/"),
            "e3": _MockRefInfo(role="link", name="Python AI Agent 全栈架构设计教程", url="/video/BV2yy411c8kE"),
        }
    )
    session = MagicMock()
    session.url = "https://www.bilibili.com"
    session.get_all_refs.return_value = refs
    session.interact = AsyncMock(return_value="ok")

    result = await get_feed_videos(session, {"max_videos": 10})
    videos = json.loads(result)

    assert len(videos) == 2
    assert videos[0]["ref"] == "e1"
    assert "超燃混剪" in videos[0]["title"]
    assert videos[0]["url"] == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert videos[1]["ref"] == "e3"
    assert videos[1]["url"] == "https://www.bilibili.com/video/BV2yy411c8kE"
    session.interact.assert_awaited_once_with(action="scroll", text="350")


@pytest.mark.asyncio
async def test_bilibili_fallback_text_extraction() -> None:
    get_feed_videos = _load_tool("bilibili", "get_feed_videos.py", "get_feed_videos")

    session = MagicMock()
    session.url = "https://www.bilibili.com"
    session.get_all_refs.return_value = MappingProxyType({})
    session.snapshot = AsyncMock(return_value=MagicMock())
    session.interact = AsyncMock(return_value="ok")
    session.extract_text = AsyncMock(
        return_value="硬核科技发布会直播回顾\n12.5万播放 · 3500弹幕 · UP主: 科技极客\n\n新一代AI大模型深度评测\n5.8万播放 · 1200点赞"
    )

    result = await get_feed_videos(session, {"max_videos": 5})
    videos = json.loads(result)

    assert len(videos) >= 1
    assert any("硬核科技" in v.get("title", "") for v in videos)


# ---------------------------------------------------------------------------
# Xiaohongshu: get_explore_notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xiaohongshu_extracts_notes_from_refs_and_handles_overlay() -> None:
    get_explore_notes = _load_tool("xiaohongshu", "get_explore_notes.py", "get_explore_notes")

    refs = MappingProxyType(
        {
            "n1": _MockRefInfo(role="link", name="上海周末宝藏咖啡馆拍照指南", url="/explore/66b8c9d0000000001f012345"),
            "n2": _MockRefInfo(role="button", name="关注", url=""),
            "n3": _MockRefInfo(role="link", name="极简风穿搭灵感合集", url="/explore/66b8cae1000000002f067890"),
        }
    )
    session = MagicMock()
    session.url = "https://www.xiaohongshu.com/explore"
    session.get_all_refs.return_value = refs
    session.interact = AsyncMock(return_value="ok")

    result = await get_explore_notes(session, {"max_notes": 10})
    notes = json.loads(result)

    assert len(notes) == 2
    assert notes[0]["ref"] == "n1"
    assert "上海周末宝藏咖啡馆" in notes[0]["title"]
    assert "https://www.xiaohongshu.com/explore/66b8c9d0" in notes[0]["url"]
    # Verifies unauthenticated overlay penetration (Escape + scroll)
    session.interact.assert_any_await(action="press", text="Escape")
    session.interact.assert_any_await(action="scroll", text="300")


@pytest.mark.asyncio
async def test_xiaohongshu_respects_max_notes() -> None:
    get_explore_notes = _load_tool("xiaohongshu", "get_explore_notes.py", "get_explore_notes")

    refs = MappingProxyType(
        {
            f"n{i}": _MockRefInfo(role="link", name=f"小红书笔记标题 #{i}", url=f"/explore/note_{i}")
            for i in range(10)
        }
    )
    session = MagicMock()
    session.url = "https://www.xiaohongshu.com/explore"
    session.get_all_refs.return_value = refs
    session.interact = AsyncMock(return_value="ok")

    result = await get_explore_notes(session, {"max_notes": 3})
    notes = json.loads(result)
    assert len(notes) == 3


# ---------------------------------------------------------------------------
# Douyin: get_user_videos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_douyin_extracts_videos_from_semantic_refs() -> None:
    get_user_videos = _load_tool("douyin", "get_user_videos.py", "get_user_videos")

    refs = MappingProxyType(
        {
            "v1": _MockRefInfo(role="link", name="周末自驾露营vlog，看日出云海", url="/video/7391234567890123456"),
            "v2": _MockRefInfo(role="link", name="摄影师老张的主页", url="/user/MS4wLjABAAA..."),
            "v3": _MockRefInfo(role="button", name="关注创作者", url=""),
        }
    )
    session = MagicMock()
    session.url = "https://www.douyin.com"
    session.get_all_refs.return_value = refs
    session.interact = AsyncMock(return_value="ok")

    result = await get_user_videos(session, {"max_videos": 10})
    videos = json.loads(result)

    assert len(videos) == 2
    assert videos[0]["ref"] == "v1"
    assert "露营vlog" in videos[0]["title"]
    assert "https://www.douyin.com/video/7391234567890123456" == videos[0]["url"]
    session.interact.assert_awaited_once_with(action="scroll", text="350")


@pytest.mark.asyncio
async def test_douyin_fallback_text_extraction() -> None:
    get_user_videos = _load_tool("douyin", "get_user_videos.py", "get_user_videos")

    session = MagicMock()
    session.url = "https://www.douyin.com"
    session.get_all_refs.return_value = MappingProxyType({})
    session.snapshot = AsyncMock(return_value=MagicMock())
    session.interact = AsyncMock(return_value="ok")
    session.extract_text = AsyncMock(
        return_value="2026最新短视频制作技巧\n15.2w 赞 · 1.8w 评论\n\nAI自动化办公实操案例\n8.6w 获赞 · 9200 转发"
    )

    result = await get_user_videos(session, {"max_videos": 5})
    videos = json.loads(result)

    assert len(videos) >= 1
    assert any("短视频制作技巧" in v.get("title", "") for v in videos)
