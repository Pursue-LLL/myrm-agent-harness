"""Distribution mode detection for source vs compiled core artifacts.

Release wheels may ship core IP modules as Nuitka-compiled native extensions
(``.so`` / ``.pyd``) via optional platform packages (``myrm-agent-harness-core-*``).
Development editable installs always use readable ``.py`` source.
"""

from __future__ import annotations

import importlib
from enum import StrEnum
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from importlib.util import find_spec
from pathlib import Path

from myrm_agent_harness._core_ip_manifest import CORE_IP_IMPORTS, CORE_IP_SOURCE_RELPATHS


class DistributionNotReadyError(RuntimeError):
    """Raised when manifest IP modules are neither present as source nor compiled."""


class DistributionMode(StrEnum):
    """How the harness package is installed on the current machine."""

    SOURCE = "source"
    COMPILED = "compiled"
    INCOMPLETE = "incomplete"


def _manifest_py_paths() -> tuple[Path, ...]:
    import myrm_agent_harness

    pkg_root = Path(myrm_agent_harness.__file__).resolve().parent
    return tuple(pkg_root / rel for rel in CORE_IP_SOURCE_RELPATHS)


def _manifest_py_present() -> bool:
    return all(path.is_file() for path in _manifest_py_paths())


def _assert_core_release_version_match() -> None:
    """Fail closed when compiled core wheel version differs from release wheel."""
    if _manifest_py_present():
        return
    if find_spec("myrm_agent_harness_core") is None:
        return

    try:
        release_version = pkg_version("myrm-agent-harness")
    except PackageNotFoundError:
        return

    import myrm_agent_harness_core

    core_version = myrm_agent_harness_core.__version__
    if core_version != release_version:
        msg = (
            "Harness distribution version mismatch: "
            f"myrm-agent-harness=={release_version} but "
            f"platform core wheel reports {core_version}. "
            "Reinstall matching core and release wheels from the same build."
        )
        raise DistributionNotReadyError(msg)


def assert_distribution_ready() -> None:
    """Verify manifest IP modules are importable (``.py`` source or compiled ``.so``)."""
    if _manifest_py_present():
        return

    missing: list[str] = []
    for import_name in CORE_IP_IMPORTS:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(import_name)

    if missing:
        joined = ", ".join(missing)
        msg = (
            "Harness distribution incomplete: core IP modules are missing. "
            "Install myrm-agent-harness-core-{platform} alongside the release wheel. "
            f"Missing: {joined}"
        )
        raise DistributionNotReadyError(msg)

    _assert_core_release_version_match()
    _assert_core_platform_key_match()


def _assert_core_platform_key_match() -> None:
    """Fail closed when the installed core wheel targets a different platform key."""
    if _manifest_py_present():
        return
    if find_spec("myrm_agent_harness_core") is None:
        return

    import myrm_agent_harness_core
    from myrm_agent_harness._runtime_platform import get_runtime_platform_key

    installed_key = myrm_agent_harness_core.get_platform_key()
    if installed_key == "unknown":
        return

    expected_key = get_runtime_platform_key()
    if installed_key != expected_key:
        msg = (
            "Harness platform core wheel mismatch: "
            f"expected myrm-agent-harness-core-{expected_key} but "
            f"installed core wheel reports platform key {installed_key!r}. "
            "Reinstall the matching platform core wheel for this machine."
        )
        raise DistributionNotReadyError(msg)


@lru_cache(maxsize=1)
def get_distribution_mode() -> DistributionMode:
    """Return whether compiled core extensions are active."""
    if _manifest_py_present():
        return DistributionMode.SOURCE
    if find_spec("myrm_agent_harness_core") is not None:
        for import_name in CORE_IP_IMPORTS:
            try:
                importlib.import_module(import_name)
            except ImportError:
                return DistributionMode.INCOMPLETE
        return DistributionMode.COMPILED
    return DistributionMode.INCOMPLETE


def is_compiled_distribution() -> bool:
    """Return True when platform core extensions are installed."""
    return get_distribution_mode() is DistributionMode.COMPILED
