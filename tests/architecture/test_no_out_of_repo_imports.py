"""Architecture gate: a repository file must not inject a path outside the repository.

This repository ships as a standalone unit. When a module climbs out of the checkout
at import time and injects that directory onto ``sys.path``, the import that follows
only resolves on a machine where the checkout happens to sit inside the private dev
shell. A standalone clone raises ModuleNotFoundError, so the file cannot run in CI
while a shell-local run reports green.

Imports that need a sibling checkout are legitimate during local integration work, so
they belong inside the test that uses them, behind an existence guard. What this gate
forbids is the import-time form: a module-level assignment that resolves above the
repository root, paired with a module-level ``sys.path`` mutation that consumes it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_PATH_INJECTION_METHODS = frozenset({"insert", "append"})

# Methods that return the same location they were called on, so they preserve a climb.
_LOCATION_PRESERVING_METHODS = frozenset({"resolve", "absolute"})

# Call wrappers that preserve the path a value points at, so the climb depth of the
# wrapped expression is the climb depth of the wrapper.
_LOCATION_PRESERVING_CALLS = frozenset({"str", "fspath"})


def _tracked_python_files() -> list[Path]:
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [(_REPO_ROOT / p) for p in paths]


def _climb_from_file(node: ast.expr) -> int | None:
    """Return how many levels ``node`` climbs above the enclosing file directory.

    ``Path(__file__)`` is the file itself, so one climb (``.parent``) lands in the
    file's own directory. ``parents[N]`` is the same as N + 1 ``.parent`` steps.
    Returns ``None`` when the expression does not derive from ``__file__``.
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _LOCATION_PRESERVING_METHODS:
            return _climb_from_file(func.value)
        if not (isinstance(func, ast.Name) and func.id == "Path"):
            return None
        if len(node.args) != 1:
            return None
        arg = node.args[0]
        if not (isinstance(arg, ast.Name) and arg.id == "__file__"):
            return None
        return 0
    if isinstance(node, ast.Attribute):
        if node.attr == "parent":
            inner = _climb_from_file(node.value)
            return None if inner is None else inner + 1
        return None
    if isinstance(node, ast.Subscript):
        if not (isinstance(node.value, ast.Attribute) and node.value.attr == "parents"):
            return None
        inner = _climb_from_file(node.value.value)
        if inner is None:
            return None
        index = node.slice
        if not (isinstance(index, ast.Constant) and isinstance(index.value, int)):
            return None
        return inner + index.value + 1
    return None


def _climb_depth_of(node: ast.expr) -> int | None:
    """Return the climb depth of ``node``, unwrapping calls that keep the same location."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _LOCATION_PRESERVING_CALLS
        and node.args
    ):
        return _climb_depth_of(node.args[0])
    return _climb_from_file(node)


def _module_level_path_aliases(tree: ast.Module) -> dict[str, int]:
    """Map module-level names to the climb depth of the path they hold."""
    aliases: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                climb = _climb_depth_of(node.value)
                if climb is not None:
                    aliases[target.id] = climb
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                climb = _climb_depth_of(node.value)
                if climb is not None:
                    aliases[node.target.id] = climb
    return aliases


def _injected_alias_name(node: ast.expr, aliases: dict[str, int]) -> str | None:
    """Return the tracked alias ``node`` refers to, unwrapping call wrappers."""
    if isinstance(node, ast.Name):
        return node.id if node.id in aliases else None
    if isinstance(node, ast.Call):
        func = node.func
        if not (isinstance(func, ast.Name) and func.id in _LOCATION_PRESERVING_CALLS):
            return None
        if not node.args:
            return None
        return _injected_alias_name(node.args[0], aliases)
    return None


def _module_level_injected_alias(tree: ast.Module, aliases: dict[str, int]) -> tuple[int, str] | None:
    """Return the injected module-level alias, if the module mutates sys.path with one."""
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        if not isinstance(func, ast.Attribute) or func.attr not in _PATH_INJECTION_METHODS:
            continue
        target = func.value
        if not (
            isinstance(target, ast.Attribute)
            and target.attr == "path"
            and isinstance(target.value, ast.Name)
            and target.value.id == "sys"
        ):
            continue
        for arg in call.args:
            name = _injected_alias_name(arg, aliases)
            if name is not None:
                return node.lineno, name
    return None


def _violation(path: Path, source: str) -> str | None:
    """Return the violation report for ``source``, or ``None`` when it is compliant."""
    tree = ast.parse(source, filename=str(path))
    aliases = _module_level_path_aliases(tree)
    if not aliases:
        return None

    injected = _module_level_injected_alias(tree, aliases)
    if injected is None:
        return None

    line_no, name = injected
    # A file's own directory sits `depth` levels below the repository root, so a
    # climb of depth + 1 reaches the root and anything beyond it leaves the tree.
    depth = len(path.relative_to(_REPO_ROOT).parent.parts)
    if aliases[name] <= depth + 1:
        return None

    rel = path.relative_to(_REPO_ROOT)
    return (
        f"{rel}:{line_no}: puts {name!r} on sys.path at import time, which resolves above the "
        "repository root. The follow-up import only works when this checkout sits inside the "
        "private dev shell, so a standalone clone fails to import this file while a shell-local "
        "run reports green. Move the import inside the test that needs it and guard it on the "
        "sibling checkout existing."
    )


# Samples that pin the detector itself. Without them the gate can be refactored into a
# no-op that still reports thousands of green tests.
_VIOLATING_SAMPLE = """
import sys
from pathlib import Path

_SHELL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_SHELL_ROOT))

from shell_scripts.ci.check_pr_hygiene import validate_pr_title
"""

_COMPLIANT_SAMPLE = """
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from myrm_agent_harness import __version__
"""

_PROBE_PATH = _REPO_ROOT / "tests" / "architecture" / "test_probe_sample.py"


def test_gate_detects_a_violation_and_allows_a_compliant_file() -> None:
    """A gate that cannot fail is not a gate: pin both outcomes of the detector."""
    assert _violation(_PROBE_PATH, _VIOLATING_SAMPLE) is not None
    assert _violation(_PROBE_PATH, _COMPLIANT_SAMPLE) is None


@pytest.mark.architecture
@pytest.mark.parametrize("path", _tracked_python_files(), ids=lambda p: p.name)
def test_no_module_level_path_injection_above_repository_root(path: Path) -> None:
    violation = _violation(path, path.read_text(encoding="utf-8"))
    if violation is not None:
        pytest.fail(violation)
