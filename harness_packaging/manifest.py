"""Load core compilation manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MANIFEST_PATH = _REPO_ROOT / "harness_packaging" / "core_manifest.yaml"
_SRC_ROOT = _REPO_ROOT / "src" / "myrm_agent_harness"


def repo_root() -> Path:
    """Return the harness repository root directory."""
    return _REPO_ROOT


@dataclass(frozen=True, slots=True)
class CoreManifest:
    """Resolved core module paths for Nuitka compilation."""

    module_paths: tuple[Path, ...]


def _resolve_module_entry(entry: str, path: Path) -> Path:
    module_path = _SRC_ROOT / f"{entry}.py"
    if not module_path.is_file():
        msg = f"Manifest module not found: {module_path} (declared in {path})"
        raise FileNotFoundError(msg)
    return module_path


def _resolve_directory_entry(entry: str, path: Path) -> list[Path]:
    directory = _SRC_ROOT / entry
    if not directory.is_dir():
        msg = f"Manifest directory not found: {directory} (declared in {path})"
        raise FileNotFoundError(msg)
    module_files = sorted(
        p for p in directory.rglob("*.py") if p.is_file() and p.name != "__init__.py"
    )
    if not module_files:
        msg = f"Manifest directory contains no Python modules: {directory}"
        raise ValueError(msg)
    return module_files


def load_core_manifest(manifest_path: Path | None = None) -> CoreManifest:
    """Parse core_manifest.yaml and resolve module paths under src/."""
    path = manifest_path or _MANIFEST_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"Invalid manifest format in {path}"
        raise ValueError(msg)

    modules = raw.get("modules", [])
    directories = raw.get("directories", [])
    if not isinstance(modules, list):
        msg = f"Manifest 'modules' must be a list: {path}"
        raise ValueError(msg)
    if not isinstance(directories, list):
        msg = f"Manifest 'directories' must be a list: {path}"
        raise ValueError(msg)
    if not modules and not directories:
        msg = f"Manifest must declare 'modules' and/or 'directories': {path}"
        raise ValueError(msg)

    resolved: dict[str, Path] = {}
    for entry in modules:
        if not isinstance(entry, str):
            msg = f"Manifest module entry must be a string, got {type(entry)!r}"
            raise ValueError(msg)
        module_path = _resolve_module_entry(entry, path)
        resolved[module_path.as_posix()] = module_path

    for entry in directories:
        if not isinstance(entry, str):
            msg = f"Manifest directory entry must be a string, got {type(entry)!r}"
            raise ValueError(msg)
        for module_path in _resolve_directory_entry(entry, path):
            resolved[module_path.as_posix()] = module_path

    return CoreManifest(module_paths=tuple(resolved[path_key] for path_key in sorted(resolved)))
