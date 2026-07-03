"""Architecture gate: core vs optional dependency layering (core slimdown)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_UV_LOCK = _REPO_ROOT / "uv.lock"

# Packages moved out of core during slimdown — must never re-enter [project].dependencies.
_MOVED_FROM_CORE: dict[str, str] = {
    "sqlalchemy": "dev",
    "prometheus-client": "observability",
    "agent-client-protocol": "acp",
    "langchain-text-splitters": "retrieval",
}

_PKG_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalize_pkg_name(specifier: str) -> str:
    match = _PKG_NAME_RE.match(specifier.strip())
    assert match is not None, f"Could not parse package name from: {specifier!r}"
    return match.group(1).lower().replace("_", "-")


def _load_pyproject() -> dict[str, object]:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def _core_dependency_names(data: dict[str, object]) -> set[str]:
    project = data["project"]
    assert isinstance(project, dict)
    deps = project.get("dependencies", [])
    assert isinstance(deps, list)
    return {_normalize_pkg_name(str(item)) for item in deps}


def _optional_extra_names(data: dict[str, object], extra: str) -> set[str]:
    project = data["project"]
    assert isinstance(project, dict)
    optional = project.get("optional-dependencies", {})
    assert isinstance(optional, dict)
    raw = optional.get(extra, [])
    assert isinstance(raw, list)
    return {_normalize_pkg_name(str(item)) for item in raw}


def _dev_group_names(data: dict[str, object], group: str) -> set[str]:
    groups = data.get("dependency-groups", {})
    assert isinstance(groups, dict)
    raw = groups.get(group, [])
    assert isinstance(raw, list)
    return {_normalize_pkg_name(str(item)) for item in raw}


def _lock_core_dependency_names() -> set[str]:
    text = _UV_LOCK.read_text(encoding="utf-8")
    block_match = re.search(
        r'name = "myrm-agent-harness"\nversion = "[^"]+"\nsource = \{ editable = "\." \}\ndependencies = \[(.*?)\]\n\n\[package\.optional-dependencies\]',
        text,
        flags=re.DOTALL,
    )
    assert block_match is not None, "myrm-agent-harness core dependencies block missing in uv.lock"
    names: set[str] = set()
    for line in block_match.group(1).splitlines():
        entry = re.search(r'name = "([^"]+)"', line)
        if entry is not None:
            names.add(entry.group(1).lower())
    return names


@pytest.mark.architecture
def test_core_dependencies_exclude_slimdown_packages() -> None:
    """Core deps must not include packages relegated to extras or dev groups."""
    data = _load_pyproject()
    core = _core_dependency_names(data)
    for pkg in _MOVED_FROM_CORE:
        assert pkg not in core, f"{pkg} must not be a core dependency (slimdown regression)"


@pytest.mark.architecture
def test_slimdown_packages_live_in_expected_extras_or_dev() -> None:
    """Moved packages must remain reachable via the documented install surface."""
    data = _load_pyproject()
    for pkg, target in _MOVED_FROM_CORE.items():
        if target == "dev":
            assert pkg in _dev_group_names(data, "dev"), f"{pkg} must stay in dependency-groups.dev"
        else:
            assert pkg in _optional_extra_names(data, target), (
                f"{pkg} must be listed under optional-dependencies.{target}"
            )


@pytest.mark.architecture
def test_core_dependency_count_is_stable() -> None:
    """Lock core footprint: 24 runtime packages after slimdown (was 28)."""
    data = _load_pyproject()
    core = _core_dependency_names(data)
    assert len(core) == 24


@pytest.mark.architecture
def test_all_extra_includes_acp() -> None:
    """[all] must pull acp alongside other product extras."""
    data = _load_pyproject()
    project = data["project"]
    assert isinstance(project, dict)
    optional = project.get("optional-dependencies", {})
    assert isinstance(optional, dict)
    all_specs = optional.get("all", [])
    assert isinstance(all_specs, list)
    assert all_specs, "[all] extra must not be empty"
    joined = " ".join(str(item) for item in all_specs)
    assert "acp" in joined


@pytest.mark.architecture
def test_uv_lock_core_matches_pyproject() -> None:
    """uv.lock editable core deps must mirror pyproject.toml (frozen install SSOT)."""
    data = _load_pyproject()
    pyproject_core = _core_dependency_names(data)
    lock_core = _lock_core_dependency_names()
    assert pyproject_core == lock_core
