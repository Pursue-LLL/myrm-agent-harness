"""Architecture gate: removed ``web_corpus`` / ``corpus=web`` must not return."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from myrm_agent_harness.toolkits.memory.agent_surface.memory_search_policy import (
    MemorySearchCorpus,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MONOREPO_ROOT = _REPO_ROOT.parent
_HARNESS_SRC = _REPO_ROOT / "src" / "myrm_agent_harness"
_WEB_CORPUS_DIR = _HARNESS_SRC / "toolkits" / "web_corpus"
_FORBIDDEN_MARKERS = (
    "web_corpus",
    "WebCorpusStore",
    "query_web_corpus",
    "enable_web_corpus",
    "allow_web",
    'corpus="web"',
    "corpus='web'",
    "toolkits/web_corpus",
)
_ALLOWLIST_SUFFIXES = (
    "tests/architecture/test_no_web_corpus_regression.py",
    "tests/toolkits/memory/test_tools.py",
    "tests/toolkits/memory/test_memory_search_policy.py",
    "tests/toolkits/memory/test_memory_agent_tool_descriptions_static.py",
    "myrm-agent-server/tests/integration/test_tool_setup_wiring.py",
)
_SCAN_ROOTS = (
    _HARNESS_SRC,
    _MONOREPO_ROOT / "myrm-agent" / "myrm-agent-server" / "app",
    _MONOREPO_ROOT / "myrm-agent" / "myrm-agent-server" / "tests",
)


def _py_files_to_scan() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if any(part in {"__pycache__", ".venv", "node_modules"} for part in path.parts):
                continue
            rel = _display_path(path)
            if any(rel.endswith(suffix) for suffix in _ALLOWLIST_SUFFIXES):
                continue
            files.append(path)
    return sorted(files)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_MONOREPO_ROOT))
    except ValueError:
        return str(path)


@pytest.mark.architecture
def test_web_corpus_package_directory_absent() -> None:
    assert not _WEB_CORPUS_DIR.exists(), (
        f"Removed web_corpus package reappeared at {_display_path(_WEB_CORPUS_DIR)}"
    )


@pytest.mark.architecture
def test_memory_search_corpus_literal_excludes_web() -> None:
    assert "web" not in get_args(MemorySearchCorpus)


@pytest.mark.architecture
def test_no_web_corpus_markers_in_python_sources() -> None:
    """Fail when production or integration sources reintroduce removed web corpus paths."""
    violations: list[str] = []
    for path in _py_files_to_scan():
        text = path.read_text(encoding="utf-8")
        for marker in _FORBIDDEN_MARKERS:
            if marker in text:
                rel = _display_path(path)
                violations.append(f"{rel}: contains {marker!r}")
    assert not violations, "web_corpus regression markers found:\n" + "\n".join(violations)
