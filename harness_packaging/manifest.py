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


def load_core_manifest(manifest_path: Path | None = None) -> CoreManifest:
    """Parse core_manifest.yaml and resolve module paths under src/."""
    path = manifest_path or _MANIFEST_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"Invalid manifest format in {path}"
        raise ValueError(msg)
    entries = raw.get("modules")
    if not isinstance(entries, list) or not entries:
        msg = f"Manifest must contain a non-empty 'modules' list: {path}"
        raise ValueError(msg)

    resolved: list[Path] = []
    for entry in entries:
        if not isinstance(entry, str):
            msg = f"Manifest module entry must be a string, got {type(entry)!r}"
            raise ValueError(msg)
        module_path = _SRC_ROOT / f"{entry}.py"
        if not module_path.is_file():
            msg = f"Manifest module not found: {module_path}"
            raise FileNotFoundError(msg)
        resolved.append(module_path)
    return CoreManifest(module_paths=tuple(resolved))
