"""Architecture gate: legacy ``myrm_agent_harness.distribution`` imports must not return."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MONOREPO_ROOT = _REPO_ROOT.parent
_HARNESS_SRC = _REPO_ROOT / "src" / "myrm_agent_harness"
_LEGACY_IMPORT_MARKERS = (
    "myrm_agent_harness.distribution",
    "from myrm_agent_harness import distribution",
)
_SCAN_ROOTS = (
    _HARNESS_SRC,
    _MONOREPO_ROOT / "myrm-agent" / "myrm-agent-server",
    _MONOREPO_ROOT / "myrm-agent" / "scripts",
    _MONOREPO_ROOT / "scripts" / "dev",
)


def _py_files_to_scan() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if any(part in {"__pycache__", ".venv", "node_modules"} for part in path.parts):
                continue
            files.append(path)
    return sorted(files)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_MONOREPO_ROOT))
    except ValueError:
        return str(path)


@pytest.mark.architecture
def test_no_legacy_distribution_import_paths_in_python_sources() -> None:
    """Fail when Python sources reintroduce removed ``distribution`` package imports."""
    violations: list[str] = []
    for path in _py_files_to_scan():
        text = path.read_text(encoding="utf-8")
        for marker in _LEGACY_IMPORT_MARKERS:
            if marker in text:
                rel = _display_path(path)
                violations.append(f"{rel}: contains {marker!r}")
    assert not violations, "Legacy distribution imports found:\n" + "\n".join(violations)
