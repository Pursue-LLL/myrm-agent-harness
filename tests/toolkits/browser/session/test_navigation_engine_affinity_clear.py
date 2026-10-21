"""Unit tests for navigation mixin engine-affinity helpers."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine
from myrm_agent_harness.toolkits.browser.pool.engine_affinity import (
    get_engine_affinity_store,
)
from myrm_agent_harness.toolkits.browser.session.browser_session_navigation_mixin import (
    _camoufox_launch_tool_error,
    _clear_engine_affinity_for_url,
)
from myrm_agent_harness.utils.errors import ToolError


@pytest.fixture()
def store_dir(tmp_path: object) -> str:
    import myrm_agent_harness.toolkits.browser.pool.engine_affinity as mod

    old_global = mod._global_store
    mod._global_store = None

    data_dir = str(tmp_path)
    with patch.dict(os.environ, {"MYRM_DATA_DIR": data_dir}):
        yield data_dir

    mod._global_store = old_global


class TestClearEngineAffinityForUrl:
    def test_clears_recorded_domain(self, store_dir: str) -> None:
        store = get_engine_affinity_store()
        store.record("blocked.example", BrowserEngine.FIREFOX_CAMOUFOX)
        assert store.get("blocked.example") is BrowserEngine.FIREFOX_CAMOUFOX

        _clear_engine_affinity_for_url("https://blocked.example/path")
        assert store.get("blocked.example") is None

    def test_noop_for_empty_netloc(self, store_dir: str) -> None:
        store = get_engine_affinity_store()
        store.record("site.com", BrowserEngine.FIREFOX_CAMOUFOX)
        _clear_engine_affinity_for_url("not-a-url")
        assert store.get("site.com") is BrowserEngine.FIREFOX_CAMOUFOX


class TestCamoufoxLaunchToolError:
    def test_raises_tool_error_with_code(self) -> None:
        cause = BrowserLaunchError("camoufox binary missing")
        with pytest.raises(ToolError) as exc_info:
            _camoufox_launch_tool_error(cause)

        err = exc_info.value
        assert err.error_code == "BROWSER_CAMOUFOX_UNAVAILABLE"
        assert "Camoufox stealth engine unavailable" in str(err)
        assert err.__cause__ is cause
