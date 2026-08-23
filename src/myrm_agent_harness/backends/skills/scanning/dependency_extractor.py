"""Skill dependency manifest extractor.

Extracts declared dependencies from skill directories and manifest files:
- package.json (npm ecosystem: dependencies, devDependencies, peerDependencies, optionalDependencies)
- requirements.txt (PyPI ecosystem: PEP 508 dependency declarations, version specifiers)
- pyproject.toml (PyPI ecosystem: PEP 621 project.dependencies, Poetry tool dependencies)

[INPUT]
- (none)

[OUTPUT]
- DeclaredDependency: structured representation of a declared dependency
- extract_dependencies_from_package_json: extract npm dependencies from package.json text
- extract_dependencies_from_requirements_txt: extract PyPI dependencies from requirements.txt text
- extract_dependencies_from_pyproject_toml: extract PyPI dependencies from pyproject.toml text
- extract_dependencies_from_uv_lock: extract PyPI locked dependencies from uv.lock text
- extract_dependencies_from_bun_lock: extract npm locked dependencies from bun.lock text
- extract_dependencies_from_package_lock_json: extract npm locked dependencies from package-lock.json text
- extract_dependencies_from_files: scan in-memory files dict for declared dependencies
- extract_skill_dependencies: scan a skill directory on disk for declared dependencies

[POS]
Supply chain dependency manifest extraction for installed and in-quarantine skills.
Feeds extracted package names and version specifiers into the OSV and offline advisory scanners.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SKIPPED_DIRS = frozenset({"node_modules", ".git", "__pycache__", ".venv", "venv", ".tox", "dist", "build"})
_MAX_DIR_DEPTH = 3

_REQ_COMMENT_RE = re.compile(r"#.*$")
_REQ_ENV_MARKER_RE = re.compile(r";.*$")
_REQ_NAME_SPEC_RE = re.compile(
    r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(?:\[[^\]]*\])?\s*([<>=!~].*)?$"
)


@dataclass(frozen=True, slots=True)
class DeclaredDependency:
    """A declared dependency extracted from a manifest file."""

    name: str
    version_spec: str
    ecosystem: str  # "npm" or "PyPI"
    file_path: str = ""
    is_dev: bool = False


def extract_dependencies_from_package_json(
    content: str,
    file_path: str = "",
) -> list[DeclaredDependency]:
    """Extract npm dependencies from package.json content."""
    dependencies: list[DeclaredDependency] = []
    try:
        pkg = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.debug("Failed to parse package.json for dependencies (%s): %s", file_path, exc)
        return dependencies

    if not isinstance(pkg, dict):
        return dependencies

    dep_sections: tuple[tuple[str, bool], ...] = (
        ("dependencies", False),
        ("devDependencies", True),
        ("peerDependencies", False),
        ("optionalDependencies", False),
    )

    for section, is_dev in dep_sections:
        section_dict = pkg.get(section)
        if isinstance(section_dict, dict):
            for pkg_name, ver_spec in section_dict.items():
                if isinstance(pkg_name, str) and pkg_name.strip():
                    normalized_spec = str(ver_spec).strip() if ver_spec is not None else ""
                    dependencies.append(
                        DeclaredDependency(
                            name=pkg_name.strip().lower(),
                            version_spec=normalized_spec,
                            ecosystem="npm",
                            file_path=file_path,
                            is_dev=is_dev,
                        )
                    )

    return dependencies


def extract_dependencies_from_requirements_txt(
    content: str,
    file_path: str = "",
) -> list[DeclaredDependency]:
    """Extract PyPI dependencies from requirements.txt content."""
    dependencies: list[DeclaredDependency] = []
    for raw_line in content.splitlines():
        line = _REQ_COMMENT_RE.sub("", raw_line).strip()
        if not line or line.startswith("-"):
            # Skip empty lines, comments, and pip flags like -r, -i, --extra-index-url
            continue

        line = _REQ_ENV_MARKER_RE.sub("", line).strip()
        match = _REQ_NAME_SPEC_RE.match(line)
        if match:
            pkg_name = match.group(1).strip().lower()
            ver_spec = (match.group(2) or "").strip()
            dependencies.append(
                DeclaredDependency(
                    name=pkg_name,
                    version_spec=ver_spec,
                    ecosystem="PyPI",
                    file_path=file_path,
                    is_dev=False,
                )
            )

    return dependencies


def extract_dependencies_from_pyproject_toml(
    content: str,
    file_path: str = "",
) -> list[DeclaredDependency]:
    """Extract PyPI dependencies from pyproject.toml content."""
    dependencies: list[DeclaredDependency] = []
    try:
        data = tomllib.loads(content)
    except Exception as exc:
        logger.debug("Failed to parse pyproject.toml for dependencies (%s): %s", file_path, exc)
        return dependencies

    if not isinstance(data, dict):
        return dependencies

    # 1. PEP 621 [project.dependencies]
    project = data.get("project")
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            for item in deps:
                if isinstance(item, str):
                    clean_item = _REQ_ENV_MARKER_RE.sub("", item).strip()
                    match = _REQ_NAME_SPEC_RE.match(clean_item)
                    if match:
                        dependencies.append(
                            DeclaredDependency(
                                name=match.group(1).strip().lower(),
                                version_spec=(match.group(2) or "").strip(),
                                ecosystem="PyPI",
                                file_path=file_path,
                                is_dev=False,
                            )
                        )

        # [project.optional-dependencies]
        opt_deps = project.get("optional-dependencies")
        if isinstance(opt_deps, dict):
            for _group, group_deps in opt_deps.items():
                if isinstance(group_deps, list):
                    for item in group_deps:
                        if isinstance(item, str):
                            clean_item = _REQ_ENV_MARKER_RE.sub("", item).strip()
                            match = _REQ_NAME_SPEC_RE.match(clean_item)
                            if match:
                                dependencies.append(
                                    DeclaredDependency(
                                        name=match.group(1).strip().lower(),
                                        version_spec=(match.group(2) or "").strip(),
                                        ecosystem="PyPI",
                                        file_path=file_path,
                                        is_dev=True,
                                    )
                                )

    # 2. Poetry [tool.poetry.dependencies] & [tool.poetry.dev-dependencies]
    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            poetry_deps = poetry.get("dependencies")
            if isinstance(poetry_deps, dict):
                for pkg_name, ver_spec in poetry_deps.items():
                    if pkg_name.lower() == "python":
                        continue
                    spec_str = ver_spec if isinstance(ver_spec, str) else str(ver_spec.get("version", "")) if isinstance(ver_spec, dict) else ""
                    dependencies.append(
                        DeclaredDependency(
                            name=pkg_name.strip().lower(),
                            version_spec=spec_str.strip(),
                            ecosystem="PyPI",
                            file_path=file_path,
                            is_dev=False,
                        )
                    )

            dev_deps = poetry.get("dev-dependencies")
            if isinstance(dev_deps, dict):
                for pkg_name, ver_spec in dev_deps.items():
                    spec_str = ver_spec if isinstance(ver_spec, str) else str(ver_spec.get("version", "")) if isinstance(ver_spec, dict) else ""
                    dependencies.append(
                        DeclaredDependency(
                            name=pkg_name.strip().lower(),
                            version_spec=spec_str.strip(),
                            ecosystem="PyPI",
                            file_path=file_path,
                            is_dev=True,
                        )
                    )

    return dependencies


def extract_dependencies_from_uv_lock(
    content: str,
    file_path: str = "",
) -> list[DeclaredDependency]:
    """Extract PyPI locked dependencies with exact versions from uv.lock content."""
    dependencies: list[DeclaredDependency] = []
    try:
        data = tomllib.loads(content)
    except Exception as exc:
        logger.debug("Failed to parse uv.lock for dependencies (%s): %s", file_path, exc)
        return dependencies

    if not isinstance(data, dict):
        return dependencies

    packages = data.get("package")
    if isinstance(packages, list):
        for pkg in packages:
            if isinstance(pkg, dict):
                pkg_name = pkg.get("name")
                pkg_ver = pkg.get("version")
                if isinstance(pkg_name, str) and pkg_name.strip():
                    name_clean = pkg_name.strip().lower()
                    ver_clean = str(pkg_ver).strip() if pkg_ver is not None else ""
                    dependencies.append(
                        DeclaredDependency(
                            name=name_clean,
                            version_spec=ver_clean,
                            ecosystem="PyPI",
                            file_path=file_path,
                            is_dev=False,
                        )
                    )

    return dependencies


def extract_dependencies_from_bun_lock(
    content: str,
    file_path: str = "",
) -> list[DeclaredDependency]:
    """Extract npm dependencies from bun.lock (v1 JSON format) content."""
    dependencies: list[DeclaredDependency] = []
    try:
        data = json.loads(content)
    except Exception as exc:
        logger.debug("Failed to parse bun.lock for dependencies (%s): %s", file_path, exc)
        return dependencies

    if not isinstance(data, dict):
        return dependencies

    workspaces = data.get("workspaces")
    if isinstance(workspaces, dict):
        for _ws_key, ws_val in workspaces.items():
            if not isinstance(ws_val, dict):
                continue
            for section, is_dev in (("dependencies", False), ("devDependencies", True), ("optionalDependencies", False)):
                deps_dict = ws_val.get(section)
                if isinstance(deps_dict, dict):
                    for pkg_name, ver_spec in deps_dict.items():
                        if isinstance(pkg_name, str) and pkg_name.strip():
                            # Remove npm spec prefixes like ^, ~, >=, etc. for lock entry base or keep raw spec
                            normalized_spec = str(ver_spec).strip() if ver_spec is not None else ""
                            dependencies.append(
                                DeclaredDependency(
                                    name=pkg_name.strip().lower(),
                                    version_spec=normalized_spec,
                                    ecosystem="npm",
                                    file_path=file_path,
                                    is_dev=is_dev,
                                )
                            )

    # In addition, check flat packages if present in bun.lock
    packages = data.get("packages")
    if isinstance(packages, dict):
        for pkg_key, pkg_info in packages.items():
            if not isinstance(pkg_info, dict):
                continue
            name = pkg_info.get("name") or pkg_key.split("@")[0]
            version = pkg_info.get("version") or ""
            if isinstance(name, str) and name.strip():
                dependencies.append(
                    DeclaredDependency(
                        name=name.strip().lower(),
                        version_spec=str(version).strip(),
                        ecosystem="npm",
                        file_path=file_path,
                        is_dev=False,
                    )
                )

    return dependencies


def extract_dependencies_from_package_lock_json(
    content: str,
    file_path: str = "",
) -> list[DeclaredDependency]:
    """Extract npm locked dependencies with exact versions from package-lock.json content."""
    dependencies: list[DeclaredDependency] = []
    try:
        data = json.loads(content)
    except Exception as exc:
        logger.debug("Failed to parse package-lock.json for dependencies (%s): %s", file_path, exc)
        return dependencies

    if not isinstance(data, dict):
        return dependencies

    packages = data.get("packages")
    if isinstance(packages, dict):
        for pkg_key, pkg_info in packages.items():
            if not pkg_key or not isinstance(pkg_info, dict):
                # Skip root workspace entry ""
                continue
            # Extract package name from "node_modules/foo" or "node_modules/@scope/foo" or name field
            raw_name = pkg_info.get("name")
            if not raw_name and "node_modules/" in pkg_key:
                raw_name = pkg_key.split("node_modules/")[-1]
            version = str(pkg_info.get("version") or "").strip()
            is_dev = bool(pkg_info.get("dev", False))

            if isinstance(raw_name, str) and raw_name.strip():
                dependencies.append(
                    DeclaredDependency(
                        name=raw_name.strip().lower(),
                        version_spec=version,
                        ecosystem="npm",
                        file_path=file_path,
                        is_dev=is_dev,
                    )
                )
    elif "dependencies" in data and isinstance(data["dependencies"], dict):
        # v1 fallback
        for pkg_name, pkg_info in data["dependencies"].items():
            if isinstance(pkg_info, dict):
                version = str(pkg_info.get("version") or "").strip()
                is_dev = bool(pkg_info.get("dev", False))
                dependencies.append(
                    DeclaredDependency(
                        name=pkg_name.strip().lower(),
                        version_spec=version,
                        ecosystem="npm",
                        file_path=file_path,
                        is_dev=is_dev,
                    )
                )

    return dependencies


def extract_dependencies_from_files(
    files: dict[str, bytes],
) -> list[DeclaredDependency]:
    """Extract all declared dependencies from an in-memory dictionary of files."""
    dependencies: list[DeclaredDependency] = []
    for filename, content in files.items():
        name_lower = Path(filename).name.lower()
        if name_lower == "package.json":
            text = content.decode("utf-8", errors="replace")
            dependencies.extend(extract_dependencies_from_package_json(text, filename))
        elif name_lower == "uv.lock":
            text = content.decode("utf-8", errors="replace")
            dependencies.extend(extract_dependencies_from_uv_lock(text, filename))
        elif name_lower == "bun.lock":
            text = content.decode("utf-8", errors="replace")
            dependencies.extend(extract_dependencies_from_bun_lock(text, filename))
        elif name_lower == "package-lock.json":
            text = content.decode("utf-8", errors="replace")
            dependencies.extend(extract_dependencies_from_package_lock_json(text, filename))
        elif name_lower.endswith(".txt") and "requirement" in name_lower:
            text = content.decode("utf-8", errors="replace")
            dependencies.extend(extract_dependencies_from_requirements_txt(text, filename))
        elif name_lower == "pyproject.toml":
            text = content.decode("utf-8", errors="replace")
            dependencies.extend(extract_dependencies_from_pyproject_toml(text, filename))

    return dependencies


def extract_skill_dependencies(skill_dir: Path | str) -> list[DeclaredDependency]:
    """Scan a skill directory on disk and extract all declared dependencies."""
    directory = Path(skill_dir).resolve()
    if not directory.is_dir():
        return []

    dependencies: list[DeclaredDependency] = []

    def _walk(current: Path, depth: int) -> None:
        if depth > _MAX_DIR_DEPTH:
            return

        try:
            entries = sorted(current.iterdir())
        except OSError as exc:
            logger.debug("Cannot read directory %s: %s", current, exc)
            return

        for entry in entries:
            if entry.name in _SKIPPED_DIRS:
                continue

            if entry.is_dir():
                _walk(entry, depth + 1)
            elif entry.is_file():
                name_lower = entry.name.lower()
                rel_path = str(entry.relative_to(directory))
                try:
                    if name_lower == "package.json":
                        text = entry.read_text(encoding="utf-8", errors="replace")
                        dependencies.extend(extract_dependencies_from_package_json(text, rel_path))
                    elif name_lower == "uv.lock":
                        text = entry.read_text(encoding="utf-8", errors="replace")
                        dependencies.extend(extract_dependencies_from_uv_lock(text, rel_path))
                    elif name_lower == "bun.lock":
                        text = entry.read_text(encoding="utf-8", errors="replace")
                        dependencies.extend(extract_dependencies_from_bun_lock(text, rel_path))
                    elif name_lower == "package-lock.json":
                        text = entry.read_text(encoding="utf-8", errors="replace")
                        dependencies.extend(extract_dependencies_from_package_lock_json(text, rel_path))
                    elif name_lower.endswith(".txt") and "requirement" in name_lower:
                        text = entry.read_text(encoding="utf-8", errors="replace")
                        dependencies.extend(extract_dependencies_from_requirements_txt(text, rel_path))
                    elif name_lower == "pyproject.toml":
                        text = entry.read_text(encoding="utf-8", errors="replace")
                        dependencies.extend(extract_dependencies_from_pyproject_toml(text, rel_path))
                except OSError as exc:
                    logger.debug("Cannot read file %s: %s", entry, exc)

    _walk(directory, 0)
    return dependencies
