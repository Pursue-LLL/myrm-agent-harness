"""Shared fixtures for web_fetch tests."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from types import ModuleType
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def install_fake_scrapling() -> Iterator[AsyncMock]:
    """Install a minimal scrapling.fetchers module for HttpFetcher tests."""
    mock_get = AsyncMock()
    fetchers_mod = ModuleType("scrapling.fetchers")
    fetchers_mod.AsyncFetcher = type("AsyncFetcher", (), {"get": staticmethod(mock_get)})

    scrapling_mod = ModuleType("scrapling")
    scrapling_mod.fetchers = fetchers_mod

    sys.modules["scrapling"] = scrapling_mod
    sys.modules["scrapling.fetchers"] = fetchers_mod
    try:
        yield mock_get
    finally:
        sys.modules.pop("scrapling.fetchers", None)
        sys.modules.pop("scrapling", None)
