"""Architecture gate: every module-level import must resolve inside this repository.

This repository ships as a standalone unit. A module that imports something only a
sibling checkout of the private dev shell provides resolves on the author's machine
and raises ``ModuleNotFoundError`` everywhere else, so a shell-local run reports green
while CI and a fresh clone fail to even collect the file.

Two real shapes of that mistake have shipped here:

- climb out of the checkout, put that directory on ``sys.path``, then import from it;
- import a module from the dev shell directly, with no path manipulation at all.

Both are caught by one rule: at module level, the full dotted path of an import must
either exist inside the repository tree, come from the standard library, or belong to
a dependency this project declares. Anything else can only resolve from outside.

Only module-level imports are inspected: an import inside a function body defers its
resolution until the call, so it cannot break collecting the module.
"""

from __future__ import annotations

import ast
import re
import sys
from functools import lru_cache
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_OWN_PACKAGE = "myrm_agent_harness"

# Import names whose distribution is named differently in ``uv.lock``. Measured from
# the current dependency set; add an entry only when a real import needs it.
_IMPORT_ALIASES = frozenset(
    {
        "acp",  # agent-client-protocol
        "bs4",  # beautifulsoup4
        "dotenv",  # python-dotenv
        "opentelemetry",  # opentelemetry-api / -sdk / -semantic-conventions
        "pil",  # pillow
        "sklearn",  # scikit-learn
        "yaml",  # PyYAML
    }
)


def _tracked_python_files() -> list[Path]:
    """Every tracked Python file that is present on disk.

    Git is the authority on what belongs to the repository, but a file can still be
    tracked while missing — a staged deletion, or a path that only exists in the index.
    Reading such a path would abort collection, so the on-disk check filters them out.
    """
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [path for path in (_REPO_ROOT / p for p in paths) if path.is_file()]


@lru_cache(maxsize=1)
def _declared_dependency_roots() -> frozenset[str]:
    """Import roots implied by the packages ``uv.lock`` pins."""
    lock = _REPO_ROOT / "uv.lock"
    if not lock.is_file():
        return frozenset()
    names = re.findall(r'^name = "([^"]+)"', lock.read_text(encoding="utf-8"), re.M)
    return frozenset(name.lower().replace("-", "_") for name in names) | _IMPORT_ALIASES


@lru_cache(maxsize=1)
def _module_stems() -> frozenset[str]:
    """Stems of tracked Python files, so flat in-repo modules resolve by name."""
    return frozenset(path.stem for path in _tracked_python_files())


def _resolves_in_repo(dotted: str) -> bool:
    """Report whether ``dotted`` names a module or namespace package in this checkout."""
    base = _REPO_ROOT.joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or base.is_dir()


def _import_roots_of(source: str) -> list[tuple[int, str]]:
    """Return ``(line, dotted path)`` for each module-level absolute import."""
    found: list[tuple[int, str]] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.append((node.lineno, node.module))
    return found


def _violation(path: Path, source: str) -> str | None:
    """Return the violation report for ``source``, or ``None`` when it is compliant."""
    declared = _declared_dependency_roots()
    stems = _module_stems()

    for line_no, dotted in _import_roots_of(source):
        root = dotted.split(".", 1)[0]
        if root in sys.stdlib_module_names or root == _OWN_PACKAGE:
            continue
        if _resolves_in_repo(dotted) or root in stems:
            continue
        if root.lower() in declared:
            continue
        rel = path.relative_to(_REPO_ROOT)
        return (
            f"{rel}:{line_no}: imports {dotted!r} at module level, which is neither in this "
            "repository nor a declared dependency. It only resolves when this checkout sits "
            "inside the private dev shell, so a standalone clone cannot import this file while "
            "a shell-local run reports green. Move the import inside the function that needs it "
            "and guard it on the sibling checkout existing."
        )
    return None


# Samples that pin the detector. Without them the rule can be refactored into a no-op
# that still reports thousands of green tests. The first two are the exact shapes that
# shipped here and turned CI red; the third is the compliant shape they were replaced by.
_CLIMBING_SAMPLE = """
import sys
from pathlib import Path

_SHELL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_SHELL_ROOT))

from shell_scripts.ci.check_pr_hygiene import validate_pr_title
"""

_DIRECT_SAMPLE = """
from scripts.ci.check_workspace_dependency_vulns import check_workspace
"""

_COMPLIANT_SAMPLE = """
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from myrm_agent_harness import __version__
from scripts.boundary_check import main
from tests.architecture import distribution_wheel_helpers
"""

_PROBE_PATH = _REPO_ROOT / "tests" / "architecture" / "test_probe_sample.py"


@pytest.mark.architecture
def test_gate_detects_both_real_shapes_and_allows_a_compliant_file() -> None:
    """A gate that cannot fail is not a gate: pin every outcome of the detector."""
    assert _violation(_PROBE_PATH, _CLIMBING_SAMPLE) is not None
    assert _violation(_PROBE_PATH, _DIRECT_SAMPLE) is not None
    assert _violation(_PROBE_PATH, _COMPLIANT_SAMPLE) is None


@pytest.mark.architecture
@pytest.mark.parametrize("path", _tracked_python_files(), ids=lambda p: p.name)
def test_no_import_outside_repository(path: Path) -> None:
    violation = _violation(path, path.read_text(encoding="utf-8"))
    if violation is not None:
        pytest.fail(violation)
