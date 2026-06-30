"""PTC builtin_registry 单元测试

Covers:
- BuiltinToolRegistry 注册/分发/查询/描述生成
- _web_fetch_handler 安全边界包装
- 重复注册警告
- 未知工具 KeyError
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.mcp.builtin_registry import (
    BUILTIN_SKILL_NAME,
    BuiltinToolEntry,
    BuiltinToolRegistry,
)


class TestBuiltinToolRegistry:
    """BuiltinToolRegistry 核心功能"""

    def test_register_and_has_tool(self) -> None:
        registry = BuiltinToolRegistry()
        handler = AsyncMock(return_value="ok")
        registry.register("test_tool", handler, "desc", {"x": "int"})
        assert registry.has_tool("test_tool")
        assert not registry.has_tool("nonexistent")

    @pytest.mark.asyncio
    async def test_dispatch_calls_handler(self) -> None:
        registry = BuiltinToolRegistry()
        handler = AsyncMock(return_value={"key": "value"})
        registry.register("my_tool", handler, "desc", {"a": "str"})

        result = await registry.dispatch("my_tool", {"a": "hello"}, trace_id="abc")
        handler.assert_awaited_once_with({"a": "hello"})
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_raises_key_error(self) -> None:
        registry = BuiltinToolRegistry()
        with pytest.raises(KeyError, match="not found"):
            await registry.dispatch("nonexistent", {})

    def test_tool_names_sorted(self) -> None:
        registry = BuiltinToolRegistry()
        for name in ["zebra", "alpha", "mid"]:
            registry.register(name, AsyncMock(), "d", {})
        assert registry.tool_names == ["alpha", "mid", "zebra"]

    def test_get_ptc_description_empty(self) -> None:
        registry = BuiltinToolRegistry()
        assert registry.get_ptc_description() == ""

    def test_get_ptc_description_contains_tool(self) -> None:
        registry = BuiltinToolRegistry()
        registry.register("demo", AsyncMock(), "A demo tool", {"q": "str"}, return_type="list")
        desc = registry.get_ptc_description()
        assert "myrm_tools.demo" in desc
        assert "A demo tool" in desc
        assert "-> list" in desc

    def test_overwrite_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = BuiltinToolRegistry()
        registry.register("dup", AsyncMock(), "first", {})
        with caplog.at_level("WARNING"):
            registry.register("dup", AsyncMock(), "second", {})
        assert "already registered" in caplog.text


class TestBuiltinSkillName:
    def test_value(self) -> None:
        assert BUILTIN_SKILL_NAME == "__builtin__"


class TestBuiltinToolEntry:
    def test_frozen(self) -> None:
        entry = BuiltinToolEntry(handler=AsyncMock(), description="d", parameters={})
        with pytest.raises(AttributeError):
            entry.description = "new"  # type: ignore[misc]

    def test_default_return_type(self) -> None:
        entry = BuiltinToolEntry(handler=AsyncMock(), description="d", parameters={})
        assert entry.return_type == "str"


class TestWebFetchHandlerSecurity:
    """验证 _web_fetch_handler 输出经过 wrap_with_external_sources_tag 安全包装"""

    @pytest.mark.asyncio
    async def test_web_fetch_wraps_output(self) -> None:
        """成功抓取时，输出必须包含 UNTRUSTED_DATA 安全边界"""
        mock_result = MagicMock()
        mock_result.url = "https://example.com"

        mock_engine = AsyncMock()
        mock_engine.crawl_many = AsyncMock(return_value=([mock_result], []))

        with (
            patch(
                "myrm_agent_harness.toolkits.web_fetch.CrawlEngine",
                return_value=mock_engine,
            ),
            patch(
                "myrm_agent_harness.utils.context_format.format_crawl_results",
                return_value="<h1>Test Page</h1>",
            ),
            patch(
                "myrm_agent_harness.utils.context_format.wrap_with_external_sources_tag",
                side_effect=lambda content, source="external": f"[WRAPPED:{source}]{content}[/WRAPPED]",
            ) as mock_wrap,
        ):
            import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

            mod._registry = None
            registry = mod.get_builtin_tool_registry()

            result = await registry.dispatch("web_fetch", {"url": "https://example.com"})
            mock_wrap.assert_called_once_with("<h1>Test Page</h1>", source="ptc_web_fetch")
            assert "[WRAPPED:ptc_web_fetch]" in str(result)

            mod._registry = None

    @pytest.mark.asyncio
    async def test_web_fetch_empty_result_not_wrapped(self) -> None:
        """format_crawl_results 返回空字符串时不应包装"""
        mock_engine = AsyncMock()
        mock_engine.crawl_many = AsyncMock(return_value=([MagicMock()], []))

        with (
            patch(
                "myrm_agent_harness.toolkits.web_fetch.CrawlEngine",
                return_value=mock_engine,
            ),
            patch(
                "myrm_agent_harness.utils.context_format.format_crawl_results",
                return_value="",
            ),
            patch(
                "myrm_agent_harness.utils.context_format.wrap_with_external_sources_tag",
            ) as mock_wrap,
        ):
            import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

            mod._registry = None
            registry = mod.get_builtin_tool_registry()

            result = await registry.dispatch("web_fetch", {"url": "https://example.com"})
            mock_wrap.assert_not_called()
            assert result == ""

            mod._registry = None

    @pytest.mark.asyncio
    async def test_web_fetch_missing_url(self) -> None:
        """缺少 url 参数应返回错误"""
        import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

        mod._registry = None
        registry = mod.get_builtin_tool_registry()

        result = await registry.dispatch("web_fetch", {})
        assert "Error" in str(result) and "url" in str(result)

        mod._registry = None

    @pytest.mark.asyncio
    async def test_web_fetch_crawl_failure(self) -> None:
        """抓取失败应返回失败消息"""
        mock_engine = AsyncMock()
        mock_engine.crawl_many = AsyncMock(return_value=([], []))

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.CrawlEngine",
            return_value=mock_engine,
        ):
            import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

            mod._registry = None
            registry = mod.get_builtin_tool_registry()

            result = await registry.dispatch("web_fetch", {"url": "https://fail.com"})
            assert "Failed" in str(result)

            mod._registry = None


class TestWebSearchHandler:
    """验证 _web_search_handler 核心路径"""

    @pytest.mark.asyncio
    async def test_web_search_missing_query(self) -> None:
        import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

        mod._registry = None
        registry = mod.get_builtin_tool_registry()

        result = await registry.dispatch("web_search", {})
        assert "Error" in str(result) and "query" in str(result)
        mod._registry = None

    @pytest.mark.asyncio
    async def test_web_search_success(self) -> None:
        mock_tools = AsyncMock()
        mock_tools.fast_search_with_questions = AsyncMock(return_value=([], "Search result"))

        with (
            patch(
                "myrm_agent_harness.toolkits.web_search.engine.SearchServiceConfig",
            ),
            patch(
                "myrm_agent_harness.toolkits.web_search.engine.WebSearchTools",
                return_value=mock_tools,
            ),
        ):
            import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

            mod._registry = None
            registry = mod.get_builtin_tool_registry()

            result = await registry.dispatch("web_search", {"query": "test query", "max_results": 3})
            assert result == "Search result"
            mock_tools.fast_search_with_questions.assert_awaited_once()
            mod._registry = None

    @pytest.mark.asyncio
    async def test_web_search_no_results(self) -> None:
        mock_tools = AsyncMock()
        mock_tools.fast_search_with_questions = AsyncMock(return_value=([], ""))

        with (
            patch(
                "myrm_agent_harness.toolkits.web_search.engine.SearchServiceConfig",
            ),
            patch(
                "myrm_agent_harness.toolkits.web_search.engine.WebSearchTools",
                return_value=mock_tools,
            ),
        ):
            import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

            mod._registry = None
            registry = mod.get_builtin_tool_registry()

            result = await registry.dispatch("web_search", {"query": "nothing"})
            assert result == "No results found."
            mod._registry = None


class TestGetBuiltinToolRegistry:
    """get_builtin_tool_registry 懒初始化和默认工具注册"""

    def test_registers_all_default_tools(self) -> None:
        import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

        mod._registry = None
        registry = mod.get_builtin_tool_registry()
        expected = {"web_search", "web_fetch", "session_store", "session_load", "session_keys", "notify"}
        assert expected.issubset(set(registry.tool_names))
        mod._registry = None

    def test_singleton_behavior(self) -> None:
        import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

        mod._registry = None
        r1 = mod.get_builtin_tool_registry()
        r2 = mod.get_builtin_tool_registry()
        assert r1 is r2
        mod._registry = None
