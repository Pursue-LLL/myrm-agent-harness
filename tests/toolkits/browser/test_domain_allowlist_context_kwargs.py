"""Unit test: domain_allowlist passed via context_kwargs (ContextFactory)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser import DomainAllowlist
from myrm_agent_harness.toolkits.browser.pool.browser_pool import ContextType
from myrm_agent_harness.toolkits.browser.pool.context_factory import ContextFactory


@pytest.mark.asyncio
async def test_context_kwargs_passes_domain_allowlist() -> None:
    """create_context extracts domain_allowlist from extra_kwargs."""
    factory = ContextFactory()

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    allowlist = DomainAllowlist.from_strings(["example.com"])
    extra_kwargs = {"domain_allowlist": allowlist, "other_key": "other_value"}

    install_domain_filter_called = False

    async def mock_install(ctx: object, al: object, *, resource_block: object | None = None) -> None:
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
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    extra_kwargs = {"other_key": "other_value"}

    install_domain_filter_called = False

    async def mock_install(ctx: object, al: object, *, resource_block: object | None = None) -> None:
        nonlocal install_domain_filter_called
        install_domain_filter_called = True

    with patch("myrm_agent_harness.toolkits.browser.domain_filter.install_domain_filter", new=mock_install):
        context = await factory.create_context(mock_browser, ContextType.CRAWL.value, extra_kwargs=extra_kwargs)

        assert context is mock_context
        assert not install_domain_filter_called
