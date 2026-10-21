"""Unit test: domain policy passed via context_kwargs (ContextFactory)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser import DomainAllowlist
from myrm_agent_harness.toolkits.browser.pool.browser_pool import ContextType
from myrm_agent_harness.toolkits.browser.pool.config import ResourceBlockConfig
from myrm_agent_harness.toolkits.browser.pool.context_factory import ContextFactory


@pytest.mark.asyncio
async def test_context_kwargs_passes_domain_allowlist() -> None:
    """create_context extracts domain_allowlist from extra_kwargs."""
    factory = ContextFactory()

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_context.set_default_timeout = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    allowlist = DomainAllowlist.from_strings(["example.com"])
    extra_kwargs = {"domain_allowlist": allowlist, "other_key": "other_value"}

    install_domain_filter_called = False

    async def mock_install(
        ctx: object,
        al: object,
        *,
        domain_blocklist: object | None = None,
        resource_block: object | None = None,
        allow_private_networks: bool = False,
    ) -> None:
        nonlocal install_domain_filter_called
        install_domain_filter_called = True
        assert ctx is mock_context
        assert al is allowlist
        assert resource_block is None

    with patch("myrm_agent_harness.toolkits.browser.domain_filter.install_domain_filter", new=mock_install):
        context = await factory.create_context(mock_browser, ContextType.CRAWL.value, extra_kwargs=extra_kwargs)

        assert context is mock_context
        assert install_domain_filter_called

        call_kwargs = mock_browser.new_context.call_args.kwargs
        assert "domain_allowlist" not in call_kwargs
        assert call_kwargs["other_key"] == "other_value"


@pytest.mark.asyncio
async def test_context_kwargs_no_domain_allowlist() -> None:
    """create_context skips install_domain_filter when no domain_allowlist."""
    factory = ContextFactory()

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_context.set_default_timeout = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    extra_kwargs = {"other_key": "other_value"}

    install_domain_filter_called = False

    async def mock_install(
        ctx: object,
        al: object,
        *,
        domain_blocklist: object | None = None,
        resource_block: object | None = None,
        allow_private_networks: bool = False,
    ) -> None:
        nonlocal install_domain_filter_called
        install_domain_filter_called = True

    with patch("myrm_agent_harness.toolkits.browser.domain_filter.install_domain_filter", new=mock_install):
        context = await factory.create_context(mock_browser, ContextType.CRAWL.value, extra_kwargs=extra_kwargs)

        assert context is mock_context
        assert not install_domain_filter_called


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [True, False])
async def test_context_kwargs_forwards_private_network_policy(flag: bool) -> None:
    """The flag reaches install_domain_filter even with resource blocking alone, and never reaches new_context."""
    factory = ContextFactory()

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_context.set_default_timeout = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    received: dict[str, object] = {}

    async def mock_install(ctx: object, al: object, **kwargs: object) -> None:
        received.update(kwargs)

    resource_block = ResourceBlockConfig(block_images=True)
    extra_kwargs = {"resource_block": resource_block, "allow_private_networks": flag, "other_key": "other_value"}

    with patch("myrm_agent_harness.toolkits.browser.domain_filter.install_domain_filter", new=mock_install):
        await factory.create_context(mock_browser, ContextType.CRAWL.value, extra_kwargs=extra_kwargs)

    assert received["allow_private_networks"] is flag
    assert received["resource_block"] is resource_block
    new_context_kwargs = mock_browser.new_context.call_args.kwargs
    assert "allow_private_networks" not in new_context_kwargs
    assert new_context_kwargs["other_key"] == "other_value"
