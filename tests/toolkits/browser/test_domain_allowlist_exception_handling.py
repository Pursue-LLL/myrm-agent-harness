"""Test: domain_allowlist exception handling and resource cleanup (ContextFactory)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser import DomainAllowlist
from myrm_agent_harness.toolkits.browser.pool.browser_pool import ContextType
from myrm_agent_harness.toolkits.browser.pool.context_factory import ContextFactory


@pytest.mark.asyncio
async def test_create_context_cleanup_on_install_failure() -> None:
    """create_context closes context if install_domain_filter fails."""
    factory = ContextFactory()

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    allowlist = DomainAllowlist.from_strings(["example.com"])

    async def failing_install(ctx: object, al: object, *, resource_block: object | None = None) -> None:
        raise RuntimeError("Install failed")

    with patch("myrm_agent_harness.toolkits.browser.domain_filter.install_domain_filter", new=failing_install):
        with pytest.raises(RuntimeError, match="Install failed"):
            await factory.create_context(
                mock_browser, ContextType.CRAWL.value, extra_kwargs={"domain_allowlist": allowlist}
            )

        mock_context.close.assert_called_once()


@pytest.mark.asyncio
async def test_create_context_no_cleanup_on_success() -> None:
    """create_context doesn't close context on successful install."""
    factory = ContextFactory()

    mock_browser = MagicMock()
    mock_context = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    allowlist = DomainAllowlist.from_strings(["example.com"])

    async def successful_install(ctx: object, al: object, *, resource_block: object | None = None) -> None:
        pass

    with patch("myrm_agent_harness.toolkits.browser.domain_filter.install_domain_filter", new=successful_install):
        context = await factory.create_context(
            mock_browser, ContextType.CRAWL.value, extra_kwargs={"domain_allowlist": allowlist}
        )

        assert context is mock_context
        mock_context.close.assert_not_called()
