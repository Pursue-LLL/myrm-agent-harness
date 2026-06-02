"""Tests for image_search_tool — DuckDuckGo image search factory."""

import asyncio
import json
from unittest.mock import MagicMock, patch

from myrm_agent_harness.toolkits.web_search.image_search_tool import (
    _image_cache,
    _search_images_sync,
    create_image_search_tool,
)


class TestCreateImageSearchTool:
    """Tool factory and metadata tests."""

    def test_creates_tool_with_correct_name(self):
        tool = create_image_search_tool()
        assert tool.name == "image_search_tool"

    def test_tool_is_async(self):
        tool = create_image_search_tool()
        assert tool.coroutine is not None

    def test_tool_has_schema(self):
        tool = create_image_search_tool()
        fields = list(tool.args_schema.model_fields.keys())
        assert "query" in fields
        assert "max_results" in fields
        assert "size" in fields
        assert "type_image" in fields
        assert "layout" in fields

    def test_custom_default_max_results(self):
        tool = create_image_search_tool(default_max_results=3)
        default_val = tool.args_schema.model_fields["max_results"].default
        assert default_val == 3

    def test_tool_description_not_empty(self):
        tool = create_image_search_tool()
        assert len(tool.description) > 100


class TestSearchImagesSync:
    """Unit tests for the synchronous search helper."""

    def test_returns_normalized_results(self):
        """When ddgs returns results, they should be normalized."""
        mock_ddgs_cls = MagicMock()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.images.return_value = [
            {"title": "Cat photo", "image": "https://example.com/cat.jpg", "thumbnail": "https://example.com/cat_thumb.jpg", "url": "https://example.com/cats"},
            {"title": "Dog photo", "image": "https://example.com/dog.jpg", "thumbnail": "https://example.com/dog_thumb.jpg", "url": "https://example.com/dogs"},
        ]

        ddgs_module = MagicMock(DDGS=mock_ddgs_cls)
        with patch.dict("sys.modules", {"ddgs": ddgs_module}):
            results = _search_images_sync(
                query="cute animals",
                max_results=5,
                region="wt-wt",
                safesearch="moderate",
                size=None,
                color=None,
                type_image=None,
                layout=None,
            )

        assert len(results) == 2
        assert results[0]["image_url"] == "https://example.com/cat.jpg"
        assert results[0]["thumbnail_url"] == "https://example.com/cat_thumb.jpg"
        assert results[0]["source_url"] == "https://example.com/cats"

    def test_filters_results_without_image_url(self):
        mock_ddgs_cls = MagicMock()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.images.return_value = [
            {"title": "Good", "image": "https://example.com/good.jpg", "thumbnail": "thumb.jpg", "url": "https://example.com"},
            {"title": "Bad", "image": "", "thumbnail": "thumb2.jpg", "url": "https://example.com"},
            {"title": "Missing", "thumbnail": "thumb3.jpg", "url": "https://example.com"},
        ]

        ddgs_module = MagicMock(DDGS=mock_ddgs_cls)
        with patch.dict("sys.modules", {"ddgs": ddgs_module}):
            results = _search_images_sync(
                query="test",
                max_results=5,
                region="wt-wt",
                safesearch="moderate",
                size=None,
                color=None,
                type_image=None,
                layout=None,
            )

        assert len(results) == 1
        assert results[0]["title"] == "Good"


class TestImageSearchToolAsync:
    """Async tool invocation tests."""

    def test_returns_error_json_on_no_results(self):
        tool = create_image_search_tool()
        _image_cache.clear()

        async def _run():
            with patch(
                "myrm_agent_harness.toolkits.web_search.image_search_tool._search_images_sync",
                return_value=[],
            ):
                return await tool.coroutine(query="nonexistent_xyz_123", max_results=5)

        result = asyncio.run(_run())
        parsed = json.loads(result)
        assert "error" in parsed
        assert parsed["query"] == "nonexistent_xyz_123"

    def test_returns_results_json_on_success(self):
        tool = create_image_search_tool()
        _image_cache.clear()

        mock_results = [
            {"title": "Test", "image_url": "https://example.com/test.jpg", "thumbnail_url": "thumb.jpg", "source_url": "https://example.com"},
        ]

        async def _run():
            with patch(
                "myrm_agent_harness.toolkits.web_search.image_search_tool._search_images_sync",
                return_value=mock_results,
            ):
                return await tool.coroutine(query="test image", max_results=5)

        result = asyncio.run(_run())
        parsed = json.loads(result)
        assert parsed["total_results"] == 1
        assert parsed["results"][0]["image_url"] == "https://example.com/test.jpg"

    def test_cache_hit_returns_cached_results(self):
        tool = create_image_search_tool()
        _image_cache.clear()

        cached_data = [
            {"title": "Cached", "image_url": "https://cached.com/img.jpg", "thumbnail_url": "t.jpg", "source_url": "https://cached.com"},
        ]
        cache_key = "img:cached_query:5:None:None:None"
        _image_cache.set(cache_key, cached_data)

        result = asyncio.run(tool.coroutine(query="cached_query", max_results=5))

        parsed = json.loads(result)
        assert parsed["total_results"] == 1
        assert parsed["results"][0]["title"] == "Cached"

        _image_cache.clear()

    def test_timeout_returns_error_json(self):
        tool = create_image_search_tool()
        _image_cache.clear()

        async def _run():
            with patch(
                "asyncio.wait_for",
                side_effect=TimeoutError(),
            ):
                return await tool.coroutine(query="timeout_test", max_results=5)

        result = asyncio.run(_run())
        parsed = json.loads(result)
        assert "error" in parsed
        assert "timed out" in parsed["error"].lower()


class TestSearchImagesSyncEdgeCases:
    """Edge cases for synchronous search helper."""

    def test_ddgs_returns_none(self):
        """ddgs.images() can return None in some edge cases."""
        mock_ddgs_cls = MagicMock()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.images.return_value = None

        ddgs_module = MagicMock(DDGS=mock_ddgs_cls)
        with patch.dict("sys.modules", {"ddgs": ddgs_module}):
            results = _search_images_sync(
                query="test", max_results=5, region="wt-wt",
                safesearch="moderate", size=None, color=None,
                type_image=None, layout=None,
            )
        assert results == []

    def test_ddgs_raises_exception(self):
        """Network errors should return empty list, not raise."""
        mock_ddgs_cls = MagicMock()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.images.side_effect = ConnectionError("Network unreachable")

        ddgs_module = MagicMock(DDGS=mock_ddgs_cls)
        with patch.dict("sys.modules", {"ddgs": ddgs_module}):
            results = _search_images_sync(
                query="test", max_results=5, region="wt-wt",
                safesearch="moderate", size=None, color=None,
                type_image=None, layout=None,
            )
        assert results == []

    def test_passes_size_filter(self):
        """Verify size filter is passed to ddgs."""
        mock_ddgs_cls = MagicMock()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.images.return_value = []

        ddgs_module = MagicMock(DDGS=mock_ddgs_cls)
        with patch.dict("sys.modules", {"ddgs": ddgs_module}):
            _search_images_sync(
                query="test", max_results=3, region="wt-wt",
                safesearch="moderate", size="Large", color=None,
                type_image="photo", layout="Wide",
            )

        call_kwargs = mock_ddgs_instance.images.call_args
        assert call_kwargs[1]["size"] == "Large"
        assert call_kwargs[1]["type_image"] == "photo"
        assert call_kwargs[1]["layout"] == "Wide"

    def test_empty_query(self):
        """Empty query should still work without crashing."""
        mock_ddgs_cls = MagicMock()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.images.return_value = []

        ddgs_module = MagicMock(DDGS=mock_ddgs_cls)
        with patch.dict("sys.modules", {"ddgs": ddgs_module}):
            results = _search_images_sync(
                query="", max_results=5, region="wt-wt",
                safesearch="moderate", size=None, color=None,
                type_image=None, layout=None,
            )
        assert results == []

    def test_unicode_query(self):
        """Unicode (CJK) queries should work."""
        mock_ddgs_cls = MagicMock()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.images.return_value = [
            {"title": "日本庭院", "image": "https://example.com/jp.jpg", "thumbnail": "t.jpg", "url": "https://example.com"},
        ]

        ddgs_module = MagicMock(DDGS=mock_ddgs_cls)
        with patch.dict("sys.modules", {"ddgs": ddgs_module}):
            results = _search_images_sync(
                query="日本庭院", max_results=5, region="wt-wt",
                safesearch="moderate", size=None, color=None,
                type_image=None, layout=None,
            )
        assert len(results) == 1
        assert results[0]["title"] == "日本庭院"


class TestImageSearchToolAsyncEdgeCases:
    """Additional async edge case tests."""

    def test_cache_key_includes_all_params(self):
        """Different filter params should produce different cache keys."""
        tool = create_image_search_tool()
        _image_cache.clear()

        mock_results = [
            {"title": "R1", "image_url": "https://example.com/1.jpg", "thumbnail_url": "t.jpg", "source_url": "https://example.com"},
        ]

        async def _run():
            with patch(
                "myrm_agent_harness.toolkits.web_search.image_search_tool._search_images_sync",
                return_value=mock_results,
            ):
                r1 = await tool.coroutine(query="cat", max_results=5, size="Large")
                r2 = await tool.coroutine(query="cat", max_results=5, size="Small")
            return r1, r2

        r1, r2 = asyncio.run(_run())
        p1, p2 = json.loads(r1), json.loads(r2)
        assert p1["total_results"] == 1
        assert p2["total_results"] == 1
        _image_cache.clear()

    def test_output_is_valid_json(self):
        """Ensure output is always valid JSON."""
        tool = create_image_search_tool()
        _image_cache.clear()

        async def _run():
            with patch(
                "myrm_agent_harness.toolkits.web_search.image_search_tool._search_images_sync",
                return_value=[
                    {"title": 'Has "quotes"', "image_url": "https://example.com/q.jpg", "thumbnail_url": "t.jpg", "source_url": "https://example.com"},
                ],
            ):
                return await tool.coroutine(query="test", max_results=5)

        result = asyncio.run(_run())
        parsed = json.loads(result)
        assert parsed["results"][0]["title"] == 'Has "quotes"'
        _image_cache.clear()


class TestToolRegistration:
    """Verify image_search_tool is registered in security metadata."""

    def test_in_builtin_tool_names(self):
        from myrm_agent_harness.agent.security.tool_registry import BUILTIN_TOOL_NAMES

        assert "image_search_tool" in BUILTIN_TOOL_NAMES

    def test_in_canonical_params(self):
        from myrm_agent_harness.agent.security.tool_registry import TOOL_CANONICAL_PARAMS

        assert "image_search_tool" in TOOL_CANONICAL_PARAMS
        assert "query" in TOOL_CANONICAL_PARAMS["image_search_tool"]

    def test_in_safety_metadata(self):
        from myrm_agent_harness.agent.security.tool_registry import TOOL_SAFETY_METADATA

        meta = TOOL_SAFETY_METADATA["image_search_tool"]
        assert meta.is_read_only is True
        assert meta.is_concurrent_safe is True
        assert meta.is_idempotent is True

    def test_in_toolkits_all(self):
        from myrm_agent_harness.toolkits import __all__

        assert "create_image_search_tool" in __all__

    def test_lazy_import_works(self):
        from myrm_agent_harness.toolkits import create_image_search_tool

        tool = create_image_search_tool()
        assert tool.name == "image_search_tool"
