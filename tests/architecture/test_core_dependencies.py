"""Architecture gate: core vs optional dependency layering and uv.lock provenance."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_UV_LOCK = _REPO_ROOT / "uv.lock"

_PROJECT_NAME = "myrm-agent-harness"

# uv writes the resolver's index and the file URLs it receives into every lock entry, so a lock created behind a
# mirror (user-level uv.toml, UV_DEFAULT_INDEX) would send CI and every other contributor to that mirror.
_PYPI_INDEX = "https://pypi.org/simple"
_PYPI_FILE_HOST = "files.pythonhosted.org"
_RELOCK_COMMAND = f"UV_DEFAULT_INDEX={_PYPI_INDEX} uv lock"

# Must remain out of [project].dependencies — each maps to an extra or dev group.
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
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


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


def _lock_packages() -> list[dict[str, object]]:
    packages = tomllib.loads(_UV_LOCK.read_text(encoding="utf-8"))["package"]
    assert isinstance(packages, list)
    return [pkg for pkg in packages if isinstance(pkg, dict)]


def _lock_core_dependency_names() -> set[str]:
    project = next((pkg for pkg in _lock_packages() if pkg.get("name") == _PROJECT_NAME), None)
    assert project is not None, f"{_PROJECT_NAME} entry missing in uv.lock"
    deps = project.get("dependencies", [])
    assert isinstance(deps, list)
    return {_normalize_pkg_name(str(dep["name"])) for dep in deps if isinstance(dep, dict)}


def _non_pypi_lock_entries(packages: Iterable[dict[str, object]]) -> list[str]:
    """Describe every package whose index or download host in the lock is not PyPI itself."""
    findings: list[str] = []
    for pkg in packages:
        name = pkg.get("name")
        source = pkg.get("source")
        assert isinstance(source, dict), f"{name}: lock entry has no source table"
        if source not in ({"registry": _PYPI_INDEX}, {"editable": "."}):
            findings.append(f"{name}: source {source}")
        wheels = pkg.get("wheels", [])
        assert isinstance(wheels, list)
        hosts = {
            str(urlsplit(str(artifact.get("url"))).hostname)
            for artifact in (pkg.get("sdist"), *wheels)
            if isinstance(artifact, dict)
        }
        findings.extend(f"{name}: download host {host}" for host in sorted(hosts - {_PYPI_FILE_HOST}))
    return findings


@pytest.mark.architecture
def test_core_dependencies_exclude_optional_only_packages() -> None:
    """Core deps must not include packages relegated to extras or dev groups."""
    data = _load_pyproject()
    core = _core_dependency_names(data)
    for pkg in _MOVED_FROM_CORE:
        assert pkg not in core, f"{pkg} must not be a core dependency"


@pytest.mark.architecture
def test_optional_only_packages_live_in_expected_extras_or_dev() -> None:
    """Optional-only packages must remain reachable via documented install surfaces."""
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
    """Lock core footprint: 24 runtime packages in [project].dependencies."""
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
    """uv.lock editable core deps must mirror pyproject.toml (``uv sync --locked`` SSOT).

    A mismatch means uv.lock is stale: run ``UV_DEFAULT_INDEX=https://pypi.org/simple uv lock`` and commit the result.
    """
    data = _load_pyproject()
    diff = _core_dependency_names(data).symmetric_difference(_lock_core_dependency_names())
    assert not diff, f"uv.lock core dependencies drift from pyproject.toml (run `{_RELOCK_COMMAND}`): {sorted(diff)}"


@pytest.mark.architecture
def test_uv_lock_resolves_from_pypi() -> None:
    """uv.lock must pin PyPI itself, never a mirror.

    Plain ``uv lock`` behind a mirror rewrites every registry source and download URL to that mirror; regenerate
    with ``UV_DEFAULT_INDEX=https://pypi.org/simple uv lock``.
    """
    findings = _non_pypi_lock_entries(_lock_packages())
    assert not findings, (
        f"uv.lock does not resolve from PyPI ({len(findings)} findings, first 3: {findings[:3]}); "
        f"regenerate it with `{_RELOCK_COMMAND}`"
    )


def _lock_entry(registry: str, file_host: str) -> dict[str, object]:
    return {
        "name": "httpx",
        "source": {"registry": registry},
        "sdist": {"url": f"https://{file_host}/packages/a1/httpx-0.28.1.tar.gz"},
        "wheels": [{"url": f"https://{file_host}/packages/a1/httpx-0.28.1-py3-none-any.whl"}],
    }


@pytest.mark.architecture
def test_lock_provenance_check_distinguishes_pypi_from_mirror() -> None:
    """Positive and negative control for the check behind ``test_uv_lock_resolves_from_pypi``."""
    project = {"name": _PROJECT_NAME, "source": {"editable": "."}}
    pypi = _lock_entry(_PYPI_INDEX, _PYPI_FILE_HOST)
    mirror = _lock_entry("https://pypi.tuna.tsinghua.edu.cn/simple", "pypi.tuna.tsinghua.edu.cn")

    assert _non_pypi_lock_entries([project, pypi]) == []
    assert _non_pypi_lock_entries([project, mirror]) == [
        "httpx: source {'registry': 'https://pypi.tuna.tsinghua.edu.cn/simple'}",
        "httpx: download host pypi.tuna.tsinghua.edu.cn",
    ]
