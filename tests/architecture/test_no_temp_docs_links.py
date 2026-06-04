"""Architecture test: tracked markdown must not link into vortexai dev-shell temp-docs/."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMP_DOCS_PATH = re.compile(r"temp-docs/[A-Za-z0-9_./-]+")


def _tracked_markdown_files() -> list[Path]:
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [_REPO_ROOT / p for p in paths]


@pytest.mark.parametrize("path", _tracked_markdown_files(), ids=lambda p: p.name)
def test_no_temp_docs_relative_links(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(_REPO_ROOT)
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = _TEMP_DOCS_PATH.search(line)
        if match:
            pytest.fail(
                f"{rel}:{line_no}: references private dev-shell path {match.group()!r}. "
                "Use in-repo _ARCH.md or maintainer-only notes without path links."
            )
