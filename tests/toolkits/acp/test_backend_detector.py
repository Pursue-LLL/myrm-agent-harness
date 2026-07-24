"""Tests for BackendDetector — CLI backend auto-detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.acp.backend_detector import (
    BackendDetector,
    DetectedBackend,
    _is_executable,
)

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning:unittest.mock")


@pytest.fixture(autouse=True)
def _reset_backend_detector_cache() -> None:
    default_ttl = BackendDetector._cache_ttl_seconds
    BackendDetector._cache_ttl_seconds = 300.0
    BackendDetector.invalidate_shared_cache()
    yield
    BackendDetector.invalidate_shared_cache()
    BackendDetector._cache_ttl_seconds = default_ttl


class TestDetectedBackend:
    def test_frozen_dataclass(self) -> None:
        db = DetectedBackend(name="claude", path="/usr/bin/claude", version="1.0.0")
        assert db.name == "claude"
        assert db.path == "/usr/bin/claude"
        assert db.version == "1.0.0"

    def test_version_optional(self) -> None:
        db = DetectedBackend(name="codex", path="/usr/bin/codex")
        assert db.version is None


class TestBackendDetectorDetect:
    @pytest.mark.asyncio
    async def test_detect_finds_nothing_when_no_backends(self) -> None:
        detector = BackendDetector()
        with patch.object(detector, "_find_executable", return_value=None):
            results = await detector.detect()
        assert results == []

    @pytest.mark.asyncio
    async def test_detect_finds_claude(self) -> None:
        detector = BackendDetector()

        def fake_find(name: str) -> str | None:
            return "/usr/local/bin/claude" if name == "claude" else None

        with (
            patch.object(detector, "_find_executable", side_effect=fake_find),
            patch.object(detector, "_get_version", return_value="1.2.3"),
        ):
            results = await detector.detect(include_version=True)

        assert len(results) == 1
        assert results[0].name == "claude"
        assert results[0].path == "/usr/local/bin/claude"
        assert results[0].version == "1.2.3"

    @pytest.mark.asyncio
    async def test_detect_without_version(self) -> None:
        detector = BackendDetector()

        with (
            patch.object(detector, "_find_executable", return_value="/bin/claude"),
            patch.object(detector, "_get_version") as mock_ver,
        ):
            results = await detector.detect(include_version=False)

        mock_ver.assert_not_called()
        assert all(r.version is None for r in results)

    @pytest.mark.asyncio
    async def test_detect_caches_results(self) -> None:
        detector = BackendDetector()
        with patch.object(detector, "_find_executable", return_value=None):
            first = await detector.detect()
            second = await detector.detect()
        assert first is second

    @pytest.mark.asyncio
    async def test_detect_cache_shared_across_instances(self) -> None:
        d1 = BackendDetector()
        d2 = BackendDetector()
        with patch.object(BackendDetector, "_find_executable", return_value=None) as mock_find:
            first = await d1.detect(include_version=False)
            second = await d2.detect(include_version=False)
        assert first is second
        assert mock_find.call_count > 0

    @pytest.mark.asyncio
    async def test_invalidate_cache_forces_redetect(self) -> None:
        detector1 = BackendDetector()
        detector2 = BackendDetector()
        call_count = 0

        def counting_find(name: str) -> str | None:
            nonlocal call_count
            call_count += 1
            return None

        with patch.object(BackendDetector, "_find_executable", side_effect=counting_find):
            await detector1.detect()
            first_count = call_count
            detector2.invalidate_cache()
            await detector1.detect()
            assert call_count > first_count

    @pytest.mark.asyncio
    async def test_detect_refresh_forces_redetect(self) -> None:
        detector = BackendDetector()
        call_count = 0

        def counting_find(name: str) -> str | None:
            nonlocal call_count
            call_count += 1
            return None

        with patch.object(BackendDetector, "_find_executable", side_effect=counting_find):
            first = await detector.detect(include_version=False)
            first_count = call_count
            second = await detector.detect(include_version=False, refresh=True)

        assert call_count > first_count
        assert first is not second

    @pytest.mark.asyncio
    async def test_detect_cache_stale_ttl_forces_redetect(self) -> None:
        detector = BackendDetector()
        BackendDetector._cache_ttl_seconds = -1.0
        call_count = 0

        def counting_find(name: str) -> str | None:
            nonlocal call_count
            call_count += 1
            return None

        with patch.object(BackendDetector, "_find_executable", side_effect=counting_find):
            first = await detector.detect(include_version=False)
            first_count = call_count
            second = await detector.detect(include_version=False)

        assert call_count > first_count
        assert first is not second


class TestFindExecutable:
    def test_finds_via_which(self) -> None:
        detector = BackendDetector()
        with patch("shutil.which", return_value="/usr/bin/claude"):
            result = detector._find_executable("claude")
        assert result == "/usr/bin/claude"

    def test_falls_back_to_common_paths(self, tmp_path: Path) -> None:
        """Test fallback to common paths when shutil.which returns None.

        Uses subprocess isolation to avoid cross-test shutil.which state leakage
        that occurs when claude CLI is installed on the system.
        """
        import subprocess
        import sys

        fake_bin = tmp_path / "claude"
        fake_bin.touch()
        fake_bin.chmod(0o755)

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"""
import shutil
shutil.which = lambda *a, **kw: None

from myrm_agent_harness.toolkits.acp.backend_detector import BackendDetector, _COMMON_PATHS
import myrm_agent_harness.toolkits.acp.backend_detector as _mod
from pathlib import Path

_mod._COMMON_PATHS = (Path("{tmp_path}"),)
detector = BackendDetector()
result = detector._find_executable("claude")
print(result or "NONE")
""",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Subprocess failed: {result.stderr}"
        assert result.stdout.strip() == str(fake_bin)

    def test_falls_back_to_npm_global(self) -> None:
        detector = BackendDetector()
        with (
            patch("shutil.which", side_effect=lambda n: "/usr/bin/npm" if n == "npm" else None),
            patch(
                "myrm_agent_harness.toolkits.acp.backend_detector._COMMON_PATHS",
                (),
            ),
            patch.object(detector, "_find_npm_global", return_value="/usr/lib/node/claude"),
        ):
            result = detector._find_executable("claude")
        assert result == "/usr/lib/node/claude"

    def test_returns_none_when_not_found(self) -> None:
        detector = BackendDetector()
        with (
            patch("shutil.which", return_value=None),
            patch(
                "myrm_agent_harness.toolkits.acp.backend_detector._COMMON_PATHS",
                (),
            ),
            patch.object(detector, "_find_npm_global", return_value=None),
        ):
            assert detector._find_executable("nonexistent") is None


class TestFindNpmGlobal:
    def test_returns_none_when_npm_not_installed(self) -> None:
        detector = BackendDetector()
        with patch("shutil.which", return_value=None):
            assert detector._find_npm_global("claude") is None

    def test_finds_in_npm_bin(self, tmp_path: Path) -> None:
        detector = BackendDetector()
        npm_bin = tmp_path / "bin"
        npm_bin.mkdir()
        fake_npm = npm_bin / "npm"
        fake_npm.touch()
        fake_npm.chmod(0o755)
        fake_claude = npm_bin / "claude"
        fake_claude.touch()
        fake_claude.chmod(0o755)

        with patch("shutil.which", return_value=str(fake_npm)):
            result = detector._find_npm_global("claude")
        assert result == str(fake_claude)


class TestGetVersion:
    @pytest.mark.asyncio
    async def test_extracts_version_string(self) -> None:
        detector = BackendDetector()
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"claude 1.5.0\n", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            version = await detector._get_version("/usr/bin/claude")
        assert version == "claude 1.5.0"

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self) -> None:
        detector = BackendDetector()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        async def _raise_timeout(awaitable: object, timeout: float) -> tuple[bytes, bytes]:
            if hasattr(awaitable, "close"):
                awaitable.close()  # type: ignore[attr-defined]
            raise TimeoutError

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=_raise_timeout):
                version = await detector._get_version("/usr/bin/claude")
        assert version is None

    @pytest.mark.asyncio
    async def test_returns_none_on_os_error(self) -> None:
        detector = BackendDetector()
        with patch("asyncio.create_subprocess_exec", side_effect=OSError("not found")):
            version = await detector._get_version("/bad/path")
        assert version is None


class TestIsExecutable:
    def test_executable_file(self, tmp_path: Path) -> None:
        f = tmp_path / "script"
        f.touch()
        f.chmod(0o755)
        assert _is_executable(f) is True

    def test_non_executable_file(self, tmp_path: Path) -> None:
        f = tmp_path / "data"
        f.touch()
        f.chmod(0o644)
        assert _is_executable(f) is False
