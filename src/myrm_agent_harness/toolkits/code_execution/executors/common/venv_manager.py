"""Virtual environment management service.

Manages shared virtual environment creation, initialization, and pip command rewriting.

[INPUT]
- toolkits.code_execution.config::ExecutionConfig (POS: Code execution configuration layer. Defines execution modes, network policies, and runtime settings for the Agent-in-Sandbox architecture.)

[OUTPUT]
- VenvManager: Shared virtual environment manager.

[POS]
Virtual environment management service.
"""

import asyncio
import logging
import sys
from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.common.subprocess_guard import guarded_communicate

logger = logging.getLogger(__name__)


def _get_default_venv_path() -> Path:
    """Resolve the default shared virtual environment path.

    Priority:
    1. MYRM_DATA_DIR environment variable + /venvs
    2. ~/.myrm/venvs (default)
    """
    import os

    data_dir = os.environ.get("MYRM_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).expanduser().resolve() / "venvs"
    return Path.home() / ".myrm" / "venvs"


DEFAULT_SHARED_VENV_PATH = _get_default_venv_path()


class VenvManager:
    """Shared virtual environment manager.

    Isolates user-installed packages from the system Python. Lazily initializes
    the venv on first use and falls back to system Python on failure.
    """

    def __init__(self, config: ExecutionConfig):
        self.config = config
        self._python_executable: str | None = None
        self._venv_initialized = False

    def get_venv_path(self) -> Path:
        """Return the shared virtual environment path."""
        if self.config.local.shared_venv_path:
            return Path(self.config.local.shared_venv_path)
        return DEFAULT_SHARED_VENV_PATH

    async def get_python_executable(self) -> str:
        """Return the Python executable path, creating the venv if needed."""
        if self._python_executable and self._venv_initialized:
            return self._python_executable

        venv_path = self.get_venv_path()
        python_path = venv_path / "bin" / "python"

        if python_path.exists():
            self._python_executable = str(python_path)
            self._venv_initialized = True
            logger.info(f" [VenvManager] Using shared venv: {venv_path}")
            return self._python_executable

        if not self.config.local.auto_create_venv:
            self._python_executable = sys.executable
            self._venv_initialized = True
            logger.warning(" [VenvManager] Using system Python (no shared venv configured)")
            return self._python_executable

        return await self._create_venv(venv_path)

    async def _create_venv(self, venv_path: Path) -> str:
        """Create a shared virtual environment.

        Falls back to system Python if creation fails.
        """
        logger.warning(f" [VenvManager] Creating shared venv: {venv_path}")
        venv_path.parent.mkdir(parents=True, exist_ok=True)

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "venv",
            str(venv_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await guarded_communicate(process, 120, label="venv create")

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            logger.error(f" [VenvManager] Failed to create venv: {error_msg}")
            self._python_executable = sys.executable
            self._venv_initialized = True
            return self._python_executable

        await self._install_base_packages(venv_path)

        python_path = venv_path / "bin" / "python"
        self._python_executable = str(python_path)
        self._venv_initialized = True
        logger.warning(f" [VenvManager] Shared venv created: {venv_path}")
        return self._python_executable

    async def _install_base_packages(self, venv_path: Path) -> None:
        """Install base packages (pip upgrade) in the venv."""
        pip_path = venv_path / "bin" / "pip"
        if not pip_path.exists():
            return

        logger.warning(" [VenvManager] Installing base packages...")
        await asyncio.create_subprocess_exec(
            str(pip_path),
            "install",
            "--upgrade",
            "pip",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def rewrite_pip_command(self, command: str) -> str:
        """Rewrite pip install commands to use the shared venv's pip.

        Args:
            command: Original command string.

        Returns:
            Rewritten command string.
        """
        stripped = command.strip()
        if not (stripped.startswith("pip install") or stripped.startswith("pip3 install")):
            return command

        await self.get_python_executable()

        venv_path = self.get_venv_path()
        pip_path = venv_path / "bin" / "pip"

        if not pip_path.exists():
            return command

        if stripped.startswith("pip3 install"):
            new_command = command.replace("pip3 install", f"{pip_path} install", 1)
        else:
            new_command = command.replace("pip install", f"{pip_path} install", 1)

        logger.warning(f" [VenvManager] Rewrote pip command: {new_command[:100]}...")
        return new_command
