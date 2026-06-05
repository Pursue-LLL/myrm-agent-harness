"""Unit tests for IsolatedToolchainManager (WeSight #1 isolated install)."""

from __future__ import annotations

import asyncio
import platform
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.acp.toolchains.manager import (
    BACKEND_NPM_MAP,
    NODE_VERSION,
    IsolatedToolchainManager,
)


class TestBackendNpmMap:
    def test_known_backends_use_official_packages(self) -> None:
        assert BACKEND_NPM_MAP["claude"] == "@anthropic-ai/claude-code"
        assert BACKEND_NPM_MAP["codex"] == "@openai/codex"
        assert BACKEND_NPM_MAP["gemini"] == "@google/gemini-cli"


@pytest.fixture
def manager(tmp_path: Path) -> IsolatedToolchainManager:
    """Manager with isolated temp base_dir (no writes under ~/.myrm-agent)."""
    m = IsolatedToolchainManager()
    m.base_dir = tmp_path
    m.node_dir = tmp_path / f"node-{NODE_VERSION}"
    m.bin_dir = tmp_path / "bin"
    m.bin_dir.mkdir(parents=True, exist_ok=True)
    return m


class TestNodeDownloadUrl:
    def test_darwin_arm64(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(platform, "machine", lambda: "arm64")
        m = IsolatedToolchainManager()
        url = m._get_node_download_url()
        assert f"node-{NODE_VERSION}-darwin-arm64" in url

    def test_linux_x64(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.setattr(platform, "machine", lambda: "x86_64")
        m = IsolatedToolchainManager()
        url = m._get_node_download_url()
        assert f"node-{NODE_VERSION}-linux-x64" in url

    def test_unsupported_os_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        m = IsolatedToolchainManager()
        with pytest.raises(RuntimeError, match="Unsupported OS"):
            m._get_node_download_url()


class TestDownloadAndExtractNode:
    @pytest.mark.asyncio
    async def test_skips_when_node_already_present(self, manager: IsolatedToolchainManager) -> None:
        (manager.node_dir / "bin").mkdir(parents=True)
        (manager.node_dir / "bin" / "node").touch()

        messages = [msg async for msg in manager._download_and_extract_node()]
        assert messages == ["Node.js environment already exists."]

    @pytest.mark.asyncio
    async def test_download_and_extract_success(
        self, manager: IsolatedToolchainManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tarfile

        folder_name = f"node-{NODE_VERSION}-darwin-arm64"

        def fake_urlretrieve(_url: str, dest: Path) -> None:
            with tarfile.open(dest, "w:gz") as tar:
                data = b"bin/node"
                import io

                info = tarfile.TarInfo(name=f"{folder_name}/bin/node")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.acp.toolchains.manager.urllib.request.urlretrieve",
            fake_urlretrieve,
        )
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.acp.toolchains.manager.platform.system",
            lambda: "darwin",
        )
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.acp.toolchains.manager.platform.machine",
            lambda: "arm64",
        )

        messages = [msg async for msg in manager._download_and_extract_node()]
        assert any("Downloading Node.js" in m for m in messages)
        assert any("setup complete" in m for m in messages)
        assert (manager.node_dir / "bin" / "node").exists()


class TestInstallBackend:
    @pytest.mark.asyncio
    async def test_unknown_backend_yields_error(self, manager: IsolatedToolchainManager) -> None:
        messages = [msg async for msg in manager.install_backend("unknown")]
        assert messages == ["Error: Unknown backend unknown."]

    @pytest.mark.asyncio
    async def test_missing_npm_after_node_setup(self, manager: IsolatedToolchainManager) -> None:
        async def fake_node_download():
            yield "Node.js environment already exists."

        manager._download_and_extract_node = fake_node_download  # type: ignore[method-assign]
        # node_dir exists but npm binary missing
        (manager.node_dir / "bin").mkdir(parents=True, exist_ok=True)

        messages = [msg async for msg in manager.install_backend("claude")]
        assert any("npm not found" in m for m in messages)


class TestInstallBackendWithMockedNpm:
    @pytest.mark.asyncio
    async def test_successful_install(self, manager: IsolatedToolchainManager) -> None:
        npm_path = manager.node_dir / "bin" / "npm"
        npm_path.parent.mkdir(parents=True)
        npm_path.touch()

        async def fake_node_download():
            yield "Node.js ready."

        manager._download_and_extract_node = fake_node_download  # type: ignore[method-assign]

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = _FakeStdout([b"npm ok\n", b""])
        mock_proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            messages = [msg async for msg in manager.install_backend("claude")]

        assert any("Successfully installed claude" in m for m in messages)
        assert any("npm ok" in m for m in messages)

    @pytest.mark.asyncio
    async def test_failed_install_exit_code(self, manager: IsolatedToolchainManager) -> None:
        npm_path = manager.node_dir / "bin" / "npm"
        npm_path.parent.mkdir(parents=True)
        npm_path.touch()

        async def fake_node_download():
            yield "Node.js ready."

        manager._download_and_extract_node = fake_node_download  # type: ignore[method-assign]

        mock_proc = MagicMock()
        mock_proc.stdout = None
        mock_proc.returncode = 1
        mock_proc.wait = AsyncMock(return_value=1)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            messages = [msg async for msg in manager.install_backend("claude")]

        assert any("exit code 1" in m for m in messages)

    @pytest.mark.asyncio
    async def test_subprocess_raises_exception(self, manager: IsolatedToolchainManager) -> None:
        npm_path = manager.node_dir / "bin" / "npm"
        npm_path.parent.mkdir(parents=True)
        npm_path.touch()

        async def fake_node_download():
            yield "Node.js ready."

        manager._download_and_extract_node = fake_node_download  # type: ignore[method-assign]

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=OSError("spawn failed"),
        ):
            messages = [msg async for msg in manager.install_backend("claude")]

        assert any("Error during installation" in m for m in messages)


class _FakeStdout:
    """Minimal async stdout reader for subprocess mocks."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)
