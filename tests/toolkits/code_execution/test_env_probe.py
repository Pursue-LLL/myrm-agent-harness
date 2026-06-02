"""Tests for toolkits/code_execution/env_probe.py — Python toolchain probe."""

from __future__ import annotations

import shutil
import subprocess
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution import env_probe


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    """Each test starts with a clean cache."""
    env_probe._reset_cache_for_tests()
    yield
    env_probe._reset_cache_for_tests()


# ---------------------------------------------------------------------------
# Silent when healthy
# ---------------------------------------------------------------------------


class TestSilentWhenHealthy:
    """The probe must emit nothing when the environment is clean."""

    def test_clean_env_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        """python3 + pip module + no PEP 668 → silent."""
        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: "3.13.3" if b == "python3" else None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: True)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: False)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: "3.13")
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: None)
        assert env_probe.get_environment_probe_line() == ""

    def test_pep668_with_uv_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        """PEP 668 with uv installed → silent (agent has viable install path)."""
        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: "3.12.4" if b == "python3" else None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: True)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: True)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: "3.12")
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: "/usr/local/bin/uv" if name == "uv" else None)
        assert env_probe.get_environment_probe_line() == ""


# ---------------------------------------------------------------------------
# Emits on real problems
# ---------------------------------------------------------------------------


class TestEmitsOnRealProblems:
    """The probe must produce a usable line for real failure modes."""

    def test_pep668_no_uv(self, monkeypatch: pytest.MonkeyPatch):
        """PEP 668 without uv → must warn."""
        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: "3.12.4" if b == "python3" else None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: True)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: True)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: "3.12")
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: None)

        line = env_probe.get_environment_probe_line()
        assert line
        assert "\n" not in line
        assert "PEP 668" in line
        assert "venv" in line or "uv" in line

    def test_python_version_mismatch(self, monkeypatch: pytest.MonkeyPatch):
        """python3 is 3.11 but pip is bound to 3.12 → mismatch warning."""
        monkeypatch.setattr(
            env_probe, "_python_version_of", lambda b: {"python3": "3.11.15", "python": None}.get(b)
        )
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: False)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: True)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: "3.12")
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: None if name == "uv" else "/usr/bin/" + name)

        line = env_probe.get_environment_probe_line()
        assert line
        assert "3.11.15" in line
        assert "no pip module" in line
        assert "mismatch" in line
        assert "PEP 668" in line

    def test_missing_python3(self, monkeypatch: pytest.MonkeyPatch):
        """If python3 isn't installed at all, say so."""
        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: False)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: False)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: None)
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: None)

        line = env_probe.get_environment_probe_line()
        assert "python3=missing" in line

    def test_no_pip_module(self, monkeypatch: pytest.MonkeyPatch):
        """python3 exists but has no pip module → output mentions it."""
        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: "3.11.2" if b == "python3" else None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: False)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: False)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: None)
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: None)

        line = env_probe.get_environment_probe_line()
        assert "no pip module" in line
        assert "3.11.2" in line

    def test_python_missing_but_python3_present(self, monkeypatch: pytest.MonkeyPatch):
        """Common on Debian: only python3 exists, no `python` alias."""
        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: "3.12.4" if b == "python3" else None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: True)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: True)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: "3.12")
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: None if name == "uv" else "/usr/bin/" + name)

        line = env_probe.get_environment_probe_line()
        assert "PEP 668" in line
        assert "python=missing" in line

    def test_uv_installed_shown(self, monkeypatch: pytest.MonkeyPatch):
        """When uv is installed but PEP-668 present, uv is mentioned."""
        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: "3.12.4" if b == "python3" else None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: False)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: True)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: None)
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)

        line = env_probe.get_environment_probe_line()
        assert "uv=installed" in line


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCaching:
    """The probe runs once per process — result is deterministic."""

    def test_result_cached(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[str] = []

        def counting_version(b: str):
            calls.append(b)
            return "3.12.4" if b == "python3" else None

        monkeypatch.setattr(env_probe, "_python_version_of", counting_version)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: True)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: False)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: "3.12")
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: None)

        env_probe.get_environment_probe_line()
        env_probe.get_environment_probe_line()
        env_probe.get_environment_probe_line()

        assert len(calls) == 2  # python3 + python, only on first call

    def test_force_refresh(self, monkeypatch: pytest.MonkeyPatch):
        """force_refresh=True clears the cache."""
        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: "3.12.4" if b == "python3" else None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: True)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: False)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: "3.12")
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: None)

        result1 = env_probe.get_environment_probe_line()

        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: False)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: None)

        result2 = env_probe.get_environment_probe_line(force_refresh=True)
        assert result1 != result2
        assert "python3=missing" in result2


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestRobustness:
    """The probe must NEVER crash the prompt build."""

    def test_subprocess_failure_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        """If every subprocess fails, just stay silent."""

        def boom(*a, **kw):
            raise OSError("simulated")

        monkeypatch.setattr(env_probe.subprocess, "run", boom)
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: "/usr/bin/" + name)
        result = env_probe.get_environment_probe_line()
        assert isinstance(result, str)

    def test_unexpected_exception_returns_empty(self, monkeypatch: pytest.MonkeyPatch):
        """Even unexpected exceptions are caught."""

        def explode(b):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(env_probe, "_python_version_of", explode)
        result = env_probe.get_environment_probe_line()
        assert result == ""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Unit tests for individual detection helpers."""

    def test_run_file_not_found(self):
        rc, _out, err = env_probe._run(["/nonexistent_binary_xyz"])
        assert rc == -1
        assert err == "not found"

    def test_run_timeout(self):
        rc, _out, err = env_probe._run(["sleep", "10"], timeout=0.1)
        assert rc == -1
        assert err == "timeout"

    def test_python_version_of_missing_binary(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert env_probe._python_version_of("nonexistent") is None

    def test_has_pip_module_missing_binary(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert env_probe._has_pip_module("nonexistent") is False

    def test_detect_pep668_missing_binary(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert env_probe._detect_pep668("nonexistent") is False

    def test_pip_python_version_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert env_probe._pip_python_version() is None

    def test_pip_python_version_parses_output(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pip")
        mock_output = "pip 24.0 from /usr/lib/python3/dist-packages/pip (python 3.12)"
        with patch.object(subprocess, "run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0, "stdout": mock_output, "stderr": ""})()
            result = env_probe._pip_python_version()
        assert result == "3.12"


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


class TestOutputFormat:
    """The output must always be a single line starting with 'Python toolchain:'."""

    def test_single_line(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(env_probe, "_python_version_of", lambda b: None)
        monkeypatch.setattr(env_probe, "_has_pip_module", lambda b: False)
        monkeypatch.setattr(env_probe, "_detect_pep668", lambda b: False)
        monkeypatch.setattr(env_probe, "_pip_python_version", lambda: None)
        monkeypatch.setattr(env_probe.shutil, "which", lambda name: None)

        line = env_probe.get_environment_probe_line()
        assert "\n" not in line
        assert line.startswith("Python toolchain:")
