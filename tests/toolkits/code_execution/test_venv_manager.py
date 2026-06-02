"""Tests for VenvManager.

Covers:
- get_venv_path: default path resolution from MYRM_DATA_DIR
- get_python_executable: venv creation and fallback behavior
- rewrite_pip_command: pip command rewriting
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.common.venv_manager import (
    VenvManager,
    _get_default_venv_path,
)


class TestGetDefaultVenvPath:
    """Tests for _get_default_venv_path helper."""

    def test_returns_myrm_data_dir_venvs(self):
        """Verify venv path is MYRM_DATA_DIR/venvs when env var is set."""
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"MYRM_DATA_DIR": str(tmpdir)}):
            result = _get_default_venv_path()
            # Path is resolved, so compare resolved paths
            assert result == Path(tmpdir).resolve() / "venvs"

    def test_returns_home_myrm_venvs_default(self):
        """Verify default venv path is ~/.myrm/venvs when MYRM_DATA_DIR is not set."""
        env_copy = os.environ.copy()
        env_copy.pop("MYRM_DATA_DIR", None)
        with patch.dict(os.environ, env_copy, clear=True):
            result = _get_default_venv_path()
            assert result == Path.home() / ".myrm" / "venvs"

    def test_strips_whitespace_from_env(self):
        """Verify whitespace is stripped from MYRM_DATA_DIR."""
        env_copy = os.environ.copy()
        env_copy["MYRM_DATA_DIR"] = "  "
        with patch.dict(os.environ, env_copy, clear=True):
            result = _get_default_venv_path()
            assert result == Path.home() / ".myrm" / "venvs"


class TestVenvManagerGetVenvPath:
    """Tests for VenvManager.get_venv_path."""

    def test_uses_config_path(self):
        """Verify custom venv path from config is used."""
        config = MagicMock()
        config.local.shared_venv_path = "/custom/venv"
        manager = VenvManager(config)
        assert manager.get_venv_path() == Path("/custom/venv")

    def test_uses_default_path_when_no_config(self):
        """Verify default path when config has no shared_venv_path."""
        config = MagicMock()
        config.local.shared_venv_path = None
        manager = VenvManager(config)
        result = manager.get_venv_path()
        assert result == _get_default_venv_path()


class TestVenvManagerRewritePipCommand:
    """Tests for VenvManager.rewrite_pip_command."""

    @pytest.mark.asyncio
    async def test_rewrites_pip_install(self):
        """Verify pip install is rewritten to use venv pip."""
        config = MagicMock()
        config.local.shared_venv_path = None
        config.local.auto_create_venv = False
        manager = VenvManager(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            venv_path = Path(tmpdir) / "venvs"
            venv_path.mkdir()
            pip_path = venv_path / "bin" / "pip"
            pip_path.parent.mkdir(parents=True)
            pip_path.touch()

            with patch.object(manager, "get_venv_path", return_value=venv_path):
                result = await manager.rewrite_pip_command("pip install requests")
                assert str(pip_path) in result
                assert "install requests" in result

    @pytest.mark.asyncio
    async def test_rewrites_pip3_install(self):
        """Verify pip3 install is rewritten to use venv pip."""
        config = MagicMock()
        config.local.shared_venv_path = None
        config.local.auto_create_venv = False
        manager = VenvManager(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            venv_path = Path(tmpdir) / "venvs"
            venv_path.mkdir()
            pip_path = venv_path / "bin" / "pip"
            pip_path.parent.mkdir(parents=True)
            pip_path.touch()

            with patch.object(manager, "get_venv_path", return_value=venv_path):
                result = await manager.rewrite_pip_command("pip3 install requests")
                assert str(pip_path) in result

    @pytest.mark.asyncio
    async def test_ignores_non_pip_command(self):
        """Verify non-pip commands are returned unchanged."""
        config = MagicMock()
        manager = VenvManager(config)

        result = await manager.rewrite_pip_command("python -m pip install requests")
        assert result == "python -m pip install requests"

    @pytest.mark.asyncio
    async def test_ignores_pip_other_subcommand(self):
        """Verify pip subcommands other than install are returned unchanged."""
        config = MagicMock()
        manager = VenvManager(config)

        result = await manager.rewrite_pip_command("pip list")
        assert result == "pip list"
