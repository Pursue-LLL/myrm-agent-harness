"""Isolated Toolchain Manager for external CLI agents.

Downloads portable environments (like Node.js) and installs CLI tools in an
isolated directory to prevent global OS environment pollution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import tarfile
import urllib.request
from collections.abc import AsyncGenerator
from pathlib import Path

logger = logging.getLogger(__name__)

TOOLCHAIN_BASE_DIR = Path.home() / ".myrm-agent" / "toolchains"
NODE_VERSION = "v20.14.0"

BACKEND_NPM_MAP = {
    "claude": "@anthropic-ai/claude-code",
    "codex": "@openai/codex",
    "gemini": "@google/gemini-cli",
}


class IsolatedToolchainManager:
    """Manages isolated toolchains for external CLI agents."""

    def __init__(self) -> None:
        self.base_dir = TOOLCHAIN_BASE_DIR
        self.node_dir = self.base_dir / f"node-{NODE_VERSION}"
        self.bin_dir = self.base_dir / "bin"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.bin_dir.mkdir(parents=True, exist_ok=True)

    def _get_node_download_url(self) -> str:
        """Determine the correct Node.js binary URL for the current OS/Arch."""
        system = platform.system().lower()
        machine = platform.machine().lower()

        if system == "darwin":
            os_name = "darwin"
            arch = "arm64" if machine == "arm64" else "x64"
        elif system == "linux":
            os_name = "linux"
            arch = "arm64" if "aarch64" in machine or "arm64" in machine else "x64"
        else:
            raise RuntimeError(f"Unsupported OS for isolated toolchain: {system}")

        return f"https://nodejs.org/dist/{NODE_VERSION}/node-{NODE_VERSION}-{os_name}-{arch}.tar.gz"

    async def _download_and_extract_node(self) -> AsyncGenerator[str]:
        """Download and extract portable Node.js."""
        if (self.node_dir / "bin" / "node").exists():
            yield "Node.js environment already exists."
            return

        url = self._get_node_download_url()
        tar_path = self.base_dir / "node.tar.gz"

        yield f"Downloading Node.js {NODE_VERSION}..."
        try:
            # Run blocking download in executor
            loop = asyncio.get_running_loop()

            # Simple file lock to prevent concurrent downloads
            lock_file = self.base_dir / ".node_download.lock"
            if lock_file.exists():
                yield "Waiting for another process to finish downloading..."
                while lock_file.exists():
                    await asyncio.sleep(1)

            try:
                lock_file.touch()
                await loop.run_in_executor(None, urllib.request.urlretrieve, url, tar_path)

                yield "Extracting Node.js..."

                def extract():
                    with tarfile.open(tar_path, "r:gz") as tar:
                        tar.extractall(path=self.base_dir)
                        # Rename extracted folder to standard node_dir
                        extracted_folder = tar.getnames()[0].split("/")[0]
                        extracted_path = self.base_dir / extracted_folder
                        if extracted_path != self.node_dir:
                            if self.node_dir.exists():
                                shutil.rmtree(self.node_dir)
                            extracted_path.rename(self.node_dir)

                await loop.run_in_executor(None, extract)
                yield "Node.js environment setup complete."
            finally:
                if lock_file.exists():
                    lock_file.unlink()
        finally:
            if tar_path.exists():
                tar_path.unlink()

    async def install_backend(self, backend_name: str) -> AsyncGenerator[str]:
        """Install a backend CLI into the isolated toolchain."""
        if backend_name not in BACKEND_NPM_MAP:
            yield f"Error: Unknown backend {backend_name}."
            return

        package_name = BACKEND_NPM_MAP[backend_name]

        # 1. Ensure Node.js is installed
        async for msg in self._download_and_extract_node():
            yield msg

        npm_path = self.node_dir / "bin" / "npm"
        if not npm_path.exists():
            yield "Error: npm not found in isolated environment."
            return

        # 2. Install the package
        yield f"Installing {package_name} via npm..."

        # Use Taobao mirror for speed in mainland China
        registry = "https://registry.npmmirror.com"

        # Install globally but with prefix set to our bin_dir
        cmd = [str(npm_path), "install", "-g", package_name, "--prefix", str(self.base_dir), "--registry", registry]

        # Setup env to use our isolated node
        env = os.environ.copy()
        env["PATH"] = f"{self.node_dir / 'bin'}:{env.get('PATH', '')}"

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env
            )

            if proc.stdout:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    yield line.decode("utf-8", errors="replace").strip()

            await proc.wait()

            if proc.returncode == 0:
                yield f"Successfully installed {backend_name}."
            else:
                yield f"Error: Installation failed with exit code {proc.returncode}."
        except Exception as e:
            yield f"Error during installation: {e}"
