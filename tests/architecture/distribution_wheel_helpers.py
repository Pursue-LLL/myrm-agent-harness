"""Shared wheel zip fixtures for distribution artifact architecture tests."""

from __future__ import annotations

import zipfile
from pathlib import Path

from harness_packaging.integrity import manifest_compiled_artifact_prefix
from harness_packaging.release import manifest_source_paths


def stub_compiled_artifact_path(manifest_py: str, *, tag: str = "cpython-313-test") -> str:
    """Return a wheel entry path that satisfies core-wheel compiled artifact rules."""
    return f"{manifest_compiled_artifact_prefix(manifest_py)}{tag}.so"


def write_minimal_release_wheel(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("myrm_agent_harness/api/__init__.py", "# public")


def write_minimal_core_wheel(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for manifest_py in manifest_source_paths():
            zf.writestr(stub_compiled_artifact_path(manifest_py), b"")
