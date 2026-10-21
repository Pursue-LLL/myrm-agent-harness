"""Tests for VenvManager.

Covers:
- get_venv_path: default path resolution from MYRM_DATA_DIR
- get_python_executable: venv creation and fallback behavior
- rewrite_pip_command: pip command rewriting
- get_python_executable: cached, reused and fallback interpreter resolution
- discard: crash-safe removal followed by a lazy rebuild
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.common.venv_manager import (
    VenvManager,
    _get_default_venv_path,
)

_MODULE = "myrm_agent_harness.toolkits.code_execution.executors.common.venv_manager"


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


class TestVenvManagerCreation:
    """Verify venv creation behavior without redundant external network upgrade."""

    @pytest.mark.asyncio
    async def test_creation_falls_back_cleanly(self):
        config = MagicMock()
        config.local.shared_venv_path = "/nonexistent/read-only/path"
        config.local.auto_create_venv = True
        manager = VenvManager(config)
        # Should gracefully fall back to sys.executable on permission error
        py_exec = await manager.get_python_executable()
        assert Path(py_exec).exists()


class TestVenvManagerInterpreterResolution:
    """Verify how get_python_executable resolves the interpreter without creating a venv."""

    @staticmethod
    def _config(venv_path: Path, *, auto_create_venv: bool) -> ExecutionConfig:
        config = ExecutionConfig()
        config.local.shared_venv_path = str(venv_path)
        config.local.auto_create_venv = auto_create_venv
        return config

    @pytest.mark.asyncio
    async def test_cached_interpreter_skips_path_resolution(self, tmp_path: Path):
        manager = VenvManager(self._config(tmp_path / "venvs", auto_create_venv=False))
        first = await manager.get_python_executable()

        with patch.object(manager, "get_venv_path", side_effect=AssertionError("cache must short-circuit")):
            assert await manager.get_python_executable() == first

    @pytest.mark.asyncio
    async def test_existing_venv_interpreter_is_reused_without_creating(self, tmp_path: Path):
        venv_path = tmp_path / "venvs"
        python_path = venv_path / "bin" / "python"
        python_path.parent.mkdir(parents=True)
        python_path.touch()
        manager = VenvManager(self._config(venv_path, auto_create_venv=True))

        with patch(f"{_MODULE}.asyncio.create_subprocess_exec", side_effect=AssertionError("must not create")):
            assert await manager.get_python_executable() == str(python_path)

    @pytest.mark.asyncio
    async def test_failed_venv_creation_falls_back_to_system_python(self, tmp_path: Path):
        manager = VenvManager(self._config(tmp_path / "venvs", auto_create_venv=True))
        failed_process = SimpleNamespace(returncode=1)

        with (
            patch(f"{_MODULE}.asyncio.create_subprocess_exec", AsyncMock(return_value=failed_process)),
            patch(f"{_MODULE}.guarded_communicate", AsyncMock(return_value=(b"", b"venv exploded"))),
        ):
            assert await manager.get_python_executable() == sys.executable

    @pytest.mark.asyncio
    async def test_pip_command_is_untouched_when_venv_has_no_pip(self, tmp_path: Path):
        manager = VenvManager(self._config(tmp_path / "venvs", auto_create_venv=False))

        assert await manager.rewrite_pip_command("pip install requests") == "pip install requests"


class TestVenvManagerDiscard:
    """Verify discard() gives the next use an empty, working interpreter."""

    @staticmethod
    def _manager(venv_path: Path) -> VenvManager:
        config = ExecutionConfig()
        config.local.shared_venv_path = str(venv_path)
        return VenvManager(config)

    @pytest.mark.asyncio
    async def test_live_manager_rebuilds_a_working_empty_venv(self, tmp_path: Path):
        """The same manager must not keep serving the interpreter path it cached before the discard."""
        venv_path = tmp_path / "venvs"
        manager = self._manager(venv_path)
        first = await manager.get_python_executable()
        (venv_path / "polluted.txt").write_text("leftover from a broken install")

        assert manager.discard() is True
        assert not venv_path.exists()
        assert not (tmp_path / "venvs.discarding").exists()

        rebuilt = await manager.get_python_executable()
        assert rebuilt == first
        assert not (venv_path / "polluted.txt").exists()
        result = subprocess.run([rebuilt, "-c", "print(40 + 2)"], capture_output=True, text=True, check=False)
        assert result.stdout.strip() == "42"

    def test_returns_false_when_no_venv_exists(self, tmp_path: Path):
        assert self._manager(tmp_path / "venvs").discard() is False

    def test_clears_trash_left_by_an_interrupted_discard(self, tmp_path: Path):
        """A crash mid-delete leaves `<venv>.discarding`; it must not block the next discard or linger."""
        venv_path = tmp_path / "venvs"
        trash = tmp_path / "venvs.discarding"
        (venv_path / "lib").mkdir(parents=True)
        (trash / "lib").mkdir(parents=True)

        assert self._manager(venv_path).discard() is True
        assert not venv_path.exists()
        assert not trash.exists()
