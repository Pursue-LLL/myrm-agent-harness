"""Unit tests for Executable Capability Probing suite.

[POS]
Harness core security test suite verifying Claude-Mem #4167 shell-immune
binary execution and tri-state (capable/incompatible/broken) capability probing.
"""

from __future__ import annotations

import sys
import pytest

from myrm_agent_harness.core.security.executable_probe import (
    ExecutableProbeResult,
    ExecutableProbeRunner,
    ExecutableProbeStatus,
    ProbeOptions,
)


def test_probe_capable_executable() -> None:
    runner = ExecutableProbeRunner()

    # Current Python executable is guaranteed present and capable
    res = runner.probe_executable(
        candidate=sys.executable,
        capability_flags=["--version"],
    )
    assert res.status == ExecutableProbeStatus.CAPABLE
    assert res.is_capable is True
    assert res.launch_failed is False
    assert res.version is not None
    assert "Python" in res.version


def test_probe_broken_non_existent_executable() -> None:
    runner = ExecutableProbeRunner()

    res = runner.probe_executable(
        candidate="/non/existent/path/to/binary_12345",
        capability_flags=["--version"],
    )
    assert res.status == ExecutableProbeStatus.BROKEN
    assert res.is_capable is False
    assert res.launch_failed is True
    assert "failed to launch" in res.detail


def test_probe_incompatible_flags() -> None:
    runner = ExecutableProbeRunner()

    # Python supports --version, but rejects bogus capability flag --nonexistent-unsupported-feature-flag
    res = runner.probe_executable(
        candidate=sys.executable,
        capability_flags=["--nonexistent-unsupported-feature-flag"],
        version_flag="--version",
        options=ProbeOptions(warm_up_retry=False),
    )
    assert res.status == ExecutableProbeStatus.INCOMPATIBLE
    assert res.is_capable is False
    assert res.launch_failed is False
    assert res.version is not None
    assert "Python" in res.version
    assert "rejected capability flags" in res.detail


def test_shell_injection_attempt_is_safely_broken() -> None:
    runner = ExecutableProbeRunner()

    # Crafted malicious candidate string with command separators
    # If passed to shell=True this could execute, but with shell=False it simply fails as ENOENT
    malicious_candidate = "python; echo INJECTED_PWNED"
    res = runner.probe_executable(
        candidate=malicious_candidate,
        capability_flags=["--version"],
    )
    assert res.status == ExecutableProbeStatus.BROKEN
    assert res.launch_failed is True
    assert res.is_capable is False
