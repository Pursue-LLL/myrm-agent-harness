"""Tests for VNC environment awareness hint (get_environment_hint / _probe_xvfb_resolution).

Covers:
- VNC unavailable → returns empty string (zero token cost)
- VNC available with resolution → includes resolution in hint
- VNC available without resolution → graceful degradation
- xdpyinfo edge cases (missing binary, timeout, bad output)
- Process-level caching (deterministic output for KV-cache safety)
- Thread safety (double-checked locking)
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.vnc import server


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the module-level cache before and after each test."""
    server._ENV_HINT_CACHE = None
    yield
    server._ENV_HINT_CACHE = None


class TestProbeXvfbResolution:
    """_probe_xvfb_resolution edge cases."""

    def test_no_xdpyinfo_binary(self):
        with patch("shutil.which", return_value=None):
            assert server._probe_xvfb_resolution() == ""

    def test_xdpyinfo_timeout(self):
        with (
            patch("shutil.which", return_value="/usr/bin/xdpyinfo"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired("xdpyinfo", 3),
            ),
        ):
            assert server._probe_xvfb_resolution() == ""

    def test_xdpyinfo_nonzero_exit(self):
        with (
            patch("shutil.which", return_value="/usr/bin/xdpyinfo"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["xdpyinfo"], returncode=1, stdout="", stderr="error",
                ),
            ),
        ):
            assert server._probe_xvfb_resolution() == ""

    def test_xdpyinfo_no_dimensions_line(self):
        with (
            patch("shutil.which", return_value="/usr/bin/xdpyinfo"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["xdpyinfo"], returncode=0,
                    stdout="screen #0:\n  some other info\n", stderr="",
                ),
            ),
        ):
            assert server._probe_xvfb_resolution() == ""

    def test_xdpyinfo_parses_resolution(self):
        xdpyinfo_output = (
            "screen #0:\n"
            "  dimensions:    1280x720 pixels (338x190 millimeters)\n"
            "  resolution:    96x96 dots per inch\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/xdpyinfo"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["xdpyinfo"], returncode=0, stdout=xdpyinfo_output, stderr="",
                ),
            ),
        ):
            assert server._probe_xvfb_resolution() == "1280x720"

    def test_xdpyinfo_oserror(self):
        with (
            patch("shutil.which", return_value="/usr/bin/xdpyinfo"),
            patch("subprocess.run", side_effect=OSError("no exec")),
        ):
            assert server._probe_xvfb_resolution() == ""


class TestGetEnvironmentHint:
    """get_environment_hint() — the public API."""

    def test_vnc_unavailable_returns_empty(self):
        with patch.object(server.VncServer, "is_available", return_value=False):
            assert server.get_environment_hint() == ""

    def test_vnc_available_with_resolution(self):
        with (
            patch.object(server.VncServer, "is_available", return_value=True),
            patch.object(server, "_probe_xvfb_resolution", return_value="1920x1080"),
        ):
            hint = server.get_environment_hint()
            assert "Visual Desktop" in hint
            assert "1920x1080" in hint
            assert "GUI applications" in hint
            assert "Visual Desktop panel" in hint

    def test_vnc_available_without_resolution(self):
        with (
            patch.object(server.VncServer, "is_available", return_value=True),
            patch.object(server, "_probe_xvfb_resolution", return_value=""),
        ):
            hint = server.get_environment_hint()
            assert "Visual Desktop" in hint
            assert "Xvfb virtual display" in hint
            assert "(" not in hint.split("display")[1].split("with")[0]

    def test_result_is_cached(self):
        with (
            patch.object(server.VncServer, "is_available", return_value=True),
            patch.object(server, "_probe_xvfb_resolution", return_value="1280x720"),
        ):
            first = server.get_environment_hint()

        server.VncServer.is_available = staticmethod(lambda: False)
        second = server.get_environment_hint()
        assert first == second, "Cached result should persist"

    def test_cache_empty_when_unavailable(self):
        with patch.object(server.VncServer, "is_available", return_value=False):
            result = server.get_environment_hint()
            assert result == ""
            assert server._ENV_HINT_CACHE == ""


    def test_hint_is_single_line(self):
        with (
            patch.object(server.VncServer, "is_available", return_value=True),
            patch.object(server, "_probe_xvfb_resolution", return_value="1280x720"),
        ):
            hint = server.get_environment_hint()
            assert "\n" not in hint

    def test_concurrent_calls_return_same_result(self):
        import concurrent.futures

        with (
            patch.object(server.VncServer, "is_available", return_value=True),
            patch.object(server, "_probe_xvfb_resolution", return_value="1920x1080"),
        ):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(server.get_environment_hint) for _ in range(8)]
                results = [f.result() for f in futures]
            assert len(set(results)) == 1, "All threads must get identical result"
            assert "1920x1080" in results[0]


class TestIsAvailableEdgeCases:
    """VncServer.is_available() — edge cases affecting get_environment_hint."""

    def test_not_posix(self):
        with patch("os.name", "nt"):
            assert server.VncServer.is_available() is False

    def test_no_display(self):
        with (
            patch("os.name", "posix"),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert server.VncServer.is_available() is False

    def test_display_set_but_no_x11vnc(self):
        with (
            patch("os.name", "posix"),
            patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False),
            patch("shutil.which", side_effect=lambda b: None),
        ):
            assert server.VncServer.is_available() is False


class TestProbeResolutionFormats:
    """Verify _probe_xvfb_resolution handles various xdpyinfo output formats."""

    @pytest.mark.parametrize(
        "output,expected",
        [
            ("  dimensions:    1920x1080 pixels (508x285 millimeters)\n", "1920x1080"),
            ("  dimensions:    3840x2160 pixels (1016x571 millimeters)\n", "3840x2160"),
            ("  dimensions:    800x600 pixels\n", "800x600"),
            ("  dimensions:    1024x768 pixels (270x203 millimeters)\n", "1024x768"),
        ],
    )
    def test_various_resolutions(self, output: str, expected: str):
        with (
            patch("shutil.which", return_value="/usr/bin/xdpyinfo"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["xdpyinfo"], returncode=0, stdout=output, stderr="",
                ),
            ),
        ):
            assert server._probe_xvfb_resolution() == expected


class TestModuleExports:
    """Verify public API exports."""

    def test_get_environment_hint_importable_from_package(self):
        from myrm_agent_harness.toolkits.vnc import get_environment_hint

        assert callable(get_environment_hint)

    def test_all_exports(self):
        from myrm_agent_harness.toolkits.vnc import __all__

        assert "get_environment_hint" in __all__
