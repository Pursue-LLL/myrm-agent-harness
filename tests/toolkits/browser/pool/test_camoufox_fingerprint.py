"""Unit tests for Camoufox fingerprint persistence and self-healing.

Covers: normal load, corrupted JSON recovery, non-dict JSON recovery,
file-not-exist generation, string JSON recovery, null JSON recovery,
empty-file recovery, and no-fingerprint-dir mode.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine, LaunchMode

FAKE_CONFIG = {
    "executable_path": "/usr/bin/camoufox",
    "env": {"MOZ_HEADLESS": "1"},
    "viewport": {"width": 1280, "height": 720},
}

_mock_browser = MagicMock()
_mock_browser._impl_obj = MagicMock()
_mock_browser._impl_obj._process = MagicMock(pid=99999)

_mock_ctx_mgr = MagicMock()
_mock_ctx_mgr.start = AsyncMock(return_value=_mock_browser)

_mock_async_camoufox_cls = MagicMock(return_value=_mock_ctx_mgr)
_mock_launch_options = MagicMock(return_value=FAKE_CONFIG.copy())

_async_api_mod = types.ModuleType("camoufox.async_api")
_async_api_mod.AsyncCamoufox = _mock_async_camoufox_cls

_utils_mod = types.ModuleType("camoufox.utils")
_utils_mod.launch_options = _mock_launch_options

_camoufox_mod = types.ModuleType("camoufox")

_originals: dict[str, types.ModuleType | None] = {}


def setup_module() -> None:
    for name in ("camoufox", "camoufox.async_api", "camoufox.utils"):
        _originals[name] = sys.modules.get(name)
    sys.modules["camoufox"] = _camoufox_mod
    sys.modules["camoufox.async_api"] = _async_api_mod
    sys.modules["camoufox.utils"] = _utils_mod


def teardown_module() -> None:
    for name, orig in _originals.items():
        if orig is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig


@pytest.fixture(autouse=True)
def _reset_mocks():
    """Reset call counts between tests."""
    _mock_async_camoufox_cls.reset_mock()
    _mock_launch_options.reset_mock()
    _mock_launch_options.return_value = FAKE_CONFIG.copy()


@pytest.fixture()
def fp_dir(tmp_path: Path) -> Path:
    d = tmp_path / "browser_fingerprints"
    d.mkdir()
    return d


def _make_launcher(fp_dir: Path | None):
    from myrm_agent_harness.toolkits.browser.pool.browser_launcher import BrowserLauncher

    return BrowserLauncher(
        launch_options={"headless": True},
        launch_mode=LaunchMode.LAUNCH,
        engine=BrowserEngine.FIREFOX_CAMOUFOX,
        fingerprint_dir=fp_dir,
    )


@pytest.mark.asyncio
async def test_normal_load(fp_dir: Path) -> None:
    """Valid fingerprint file is loaded without regeneration."""
    fp_file = fp_dir / "camoufox_fingerprint.json"
    fp_file.write_text(json.dumps(FAKE_CONFIG), encoding="utf-8")

    launcher = _make_launcher(fp_dir)
    await launcher.create_browser()

    _mock_launch_options.assert_not_called()
    _mock_async_camoufox_cls.assert_called_once()
    assert _mock_async_camoufox_cls.call_args[1]["from_options"] == FAKE_CONFIG


@pytest.mark.asyncio
async def test_corrupted_json_self_heals(fp_dir: Path) -> None:
    """Corrupted JSON triggers delete + regeneration."""
    fp_file = fp_dir / "camoufox_fingerprint.json"
    fp_file.write_text('{"broken json', encoding="utf-8")

    launcher = _make_launcher(fp_dir)
    await launcher.create_browser()

    _mock_launch_options.assert_called_once()
    saved = json.loads(fp_file.read_text(encoding="utf-8"))
    assert isinstance(saved, dict)


@pytest.mark.asyncio
async def test_non_dict_json_self_heals(fp_dir: Path) -> None:
    """Valid JSON that is not a dict triggers delete + regeneration."""
    fp_file = fp_dir / "camoufox_fingerprint.json"
    fp_file.write_text("[1, 2, 3]", encoding="utf-8")

    launcher = _make_launcher(fp_dir)
    await launcher.create_browser()

    _mock_launch_options.assert_called_once()
    saved = json.loads(fp_file.read_text(encoding="utf-8"))
    assert isinstance(saved, dict)


@pytest.mark.asyncio
async def test_file_not_exist_generates(fp_dir: Path) -> None:
    """When no fingerprint file exists, config is generated and saved."""
    fp_file = fp_dir / "camoufox_fingerprint.json"
    assert not fp_file.exists()

    launcher = _make_launcher(fp_dir)
    await launcher.create_browser()

    _mock_launch_options.assert_called_once()
    assert fp_file.exists()
    saved = json.loads(fp_file.read_text(encoding="utf-8"))
    assert isinstance(saved, dict)


@pytest.mark.asyncio
async def test_string_json_self_heals(fp_dir: Path) -> None:
    """String JSON (valid but not dict) triggers self-heal."""
    fp_file = fp_dir / "camoufox_fingerprint.json"
    fp_file.write_text('"just a string"', encoding="utf-8")

    launcher = _make_launcher(fp_dir)
    await launcher.create_browser()

    _mock_launch_options.assert_called_once()


@pytest.mark.asyncio
async def test_null_json_self_heals(fp_dir: Path) -> None:
    """JSON null (parses to None, not dict) triggers self-heal."""
    fp_file = fp_dir / "camoufox_fingerprint.json"
    fp_file.write_text("null", encoding="utf-8")

    launcher = _make_launcher(fp_dir)
    await launcher.create_browser()

    _mock_launch_options.assert_called_once()
    saved = json.loads(fp_file.read_text(encoding="utf-8"))
    assert isinstance(saved, dict)


@pytest.mark.asyncio
async def test_empty_file_self_heals(fp_dir: Path) -> None:
    """Empty file triggers JSONDecodeError → self-heal."""
    fp_file = fp_dir / "camoufox_fingerprint.json"
    fp_file.write_text("", encoding="utf-8")

    launcher = _make_launcher(fp_dir)
    await launcher.create_browser()

    _mock_launch_options.assert_called_once()
    saved = json.loads(fp_file.read_text(encoding="utf-8"))
    assert isinstance(saved, dict)


@pytest.mark.asyncio
async def test_no_fingerprint_dir_generates_without_saving() -> None:
    """When fingerprint_dir is None, config is generated but not persisted."""
    launcher = _make_launcher(None)
    await launcher.create_browser()

    _mock_launch_options.assert_called_once()
    _mock_async_camoufox_cls.assert_called_once()
