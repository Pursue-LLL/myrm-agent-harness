"""Nuitka compile path helpers for manifest module files.

[INPUT]
- pathlib.Path manifest module file under ``myrm_agent_harness/``

[OUTPUT]
- nuitka_compile_input(): Path for ``nuitka --module``
- nuitka_artifact_stem(): Expected compiled artifact filename stem

[POS]
Build-time Nuitka input mapping. Package ``__init__.py`` files compile their directory.
"""

from __future__ import annotations

from pathlib import Path


def nuitka_compile_input(module_file: Path) -> Path:
    """Return the path to pass to ``nuitka --module``.

    Package ``__init__.py`` files must compile their parent directory, not the file itself.
    """
    if module_file.name == "__init__.py":
        return module_file.parent
    return module_file


def nuitka_artifact_stem(module_file: Path) -> str:
    """Return the expected compiled artifact filename stem."""
    if module_file.name == "__init__.py":
        return module_file.parent.name
    return module_file.stem
