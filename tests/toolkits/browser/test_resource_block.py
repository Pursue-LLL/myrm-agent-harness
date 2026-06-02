"""Tests for resource blocking configuration."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.pool import (
    BrowserPoolConfig,
    GlobalBrowserPool,
    ResourceBlockConfig,
)


@pytest.mark.asyncio
async def test_resource_block_config_creation() -> None:
    """Test ResourceBlockConfig creation with different settings."""
    config = ResourceBlockConfig(
        block_images=True,
        block_stylesheets=True,
        block_scripts=False,
        block_fonts=True,
        block_media=True,
    )

    assert config.block_images is True
    assert config.block_stylesheets is True
    assert config.block_scripts is False
    assert config.block_fonts is True
    assert config.block_media is True


@pytest.mark.asyncio
async def test_resource_block_default_config() -> None:
    """Test ResourceBlockConfig default values (all False)."""
    config = ResourceBlockConfig()

    assert config.block_images is False
    assert config.block_stylesheets is False
    assert config.block_scripts is False
    assert config.block_fonts is False
    assert config.block_media is False


@pytest.mark.asyncio
async def test_browser_pool_config_with_resource_block() -> None:
    """Test BrowserPoolConfig includes ResourceBlockConfig."""
    config = BrowserPoolConfig(
        max_concurrent_pages=10,
        resource_block=ResourceBlockConfig(
            block_images=True,
            block_stylesheets=True,
        ),
    )

    assert config.resource_block.block_images is True
    assert config.resource_block.block_stylesheets is True
    assert config.resource_block.block_scripts is False


@pytest.mark.asyncio
async def test_defensive_preset_has_resource_block() -> None:
    """Test defensive preset includes resource blocking."""
    config = BrowserPoolConfig.defensive()

    assert config.resource_block.block_images is True
    assert config.resource_block.block_stylesheets is True
    assert config.resource_block.block_fonts is True
    assert config.resource_block.block_media is True
    assert config.resource_block.block_scripts is False


@pytest.mark.asyncio
async def test_minimal_preset_no_resource_block() -> None:
    """Test minimal preset does not block resources."""
    config = BrowserPoolConfig.minimal()

    assert config.resource_block.block_images is False
    assert config.resource_block.block_stylesheets is False
    assert config.resource_block.block_scripts is False
    assert config.resource_block.block_fonts is False
    assert config.resource_block.block_media is False


@pytest.mark.asyncio
async def test_global_browser_pool_with_resource_block() -> None:
    """Test GlobalBrowserPool initialization with resource blocking config."""
    config = BrowserPoolConfig(
        max_concurrent_pages=5,
        resource_block=ResourceBlockConfig(block_images=True),
    )

    pool = GlobalBrowserPool(max_browsers=1, config=config)

    assert pool._config.resource_block.block_images is True

    await pool.shutdown()
