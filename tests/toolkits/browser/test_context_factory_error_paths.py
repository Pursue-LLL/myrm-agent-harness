"""Tests for ContextFactory error handling and default_emulation paths"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType
from myrm_agent_harness.toolkits.browser.pool.context_factory import ContextFactory
from myrm_agent_harness.toolkits.browser.pool.emulation import EmulationConfig


@pytest.mark.asyncio
async def test_create_context_domain_filter_install_failure():
    """测试：domain_filter 安装失败时清理 context"""
    factory = ContextFactory()

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    # Mock domain_filter.install_domain_filter 抛出异常（它是在方法内部导入的）
    with patch(
        "myrm_agent_harness.toolkits.browser.domain_filter.install_domain_filter",
        side_effect=RuntimeError("Domain filter installation failed"),
    ):
        extra_kwargs = {"domain_allowlist": ["example.com"]}

        with pytest.raises(RuntimeError, match="Domain filter installation failed"):
            await factory.create_context(mock_browser, ContextType.CRAWL, extra_kwargs=extra_kwargs)

        # 验证 context 被清理
        mock_context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_install_domain_filter_called():
    """测试：_install_domain_filter 方法被正确调用"""
    factory = ContextFactory()

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    # Mock domain_filter.install_domain_filter 成功
    with patch("myrm_agent_harness.toolkits.browser.domain_filter.install_domain_filter") as mock_install:
        extra_kwargs = {"domain_allowlist": ["example.com"], "resource_block": {"block_images": True}}

        context = await factory.create_context(mock_browser, ContextType.CRAWL, extra_kwargs=extra_kwargs)

        # 验证 install_domain_filter 被调用
        mock_install.assert_awaited_once()
        call_args = mock_install.call_args

        # 检查参数（使用 args 或 kwargs）
        if len(call_args[0]) >= 2:
            assert call_args[0][0] == mock_context
            assert call_args[0][1] == ["example.com"]

        assert context == mock_context


class TestContextFactoryDefaultEmulation:
    """Tests for default_emulation fallback in ContextFactory."""

    def test_init_stores_default_emulation(self):
        emul = EmulationConfig(permissions=("clipboard-read", "clipboard-write"))
        factory = ContextFactory(default_emulation=emul)
        assert factory._default_emulation is emul

    def test_init_without_default_emulation(self):
        factory = ContextFactory()
        assert factory._default_emulation is None

    def test_build_context_options_uses_default_when_no_explicit(self):
        emul = EmulationConfig(permissions=("clipboard-read", "clipboard-write"))
        factory = ContextFactory(default_emulation=emul)
        opts = factory._build_context_options("crawl", emulation=None, extra_kwargs=None)
        assert opts["permissions"] == ["clipboard-read", "clipboard-write"]

    def test_build_context_options_explicit_overrides_default(self):
        default_emul = EmulationConfig(permissions=("clipboard-read",))
        explicit_emul = EmulationConfig(permissions=("geolocation", "notifications"))
        factory = ContextFactory(default_emulation=default_emul)
        opts = factory._build_context_options("crawl", emulation=explicit_emul, extra_kwargs=None)
        assert opts["permissions"] == ["geolocation", "notifications"]

    def test_build_context_options_no_emulation_at_all(self):
        factory = ContextFactory()
        opts = factory._build_context_options("crawl", emulation=None, extra_kwargs=None)
        assert "permissions" not in opts

    def test_build_context_options_stealth_with_default_emulation(self):
        emul = EmulationConfig(permissions=("clipboard-read", "clipboard-write"))
        factory = ContextFactory(default_emulation=emul)
        opts = factory._build_context_options("stealth", emulation=None, extra_kwargs=None)
        assert opts["permissions"] == ["clipboard-read", "clipboard-write"]
        assert "user_agent" in opts
