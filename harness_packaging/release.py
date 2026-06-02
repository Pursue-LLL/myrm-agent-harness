"""Release wheel utilities — strip core IP source from distributable wheels."""

from __future__ import annotations

import zipfile
from pathlib import Path

from harness_packaging.manifest import load_core_manifest, repo_root


def manifest_source_paths() -> tuple[str, ...]:
    """Return wheel-internal paths (posix) for manifest ``.py`` files to remove."""
    manifest = load_core_manifest()
    root = repo_root()
    paths: list[str] = []
    for module_file in manifest.module_paths:
        rel = module_file.relative_to(root / "src" / "myrm_agent_harness")
        paths.append(f"myrm_agent_harness/{rel.as_posix()}")
    return tuple(paths)


def strip_manifest_sources_from_wheel(
    wheel_path: Path,
    output_path: Path | None = None,
    *,
    in_place: bool = False,
) -> Path:
    """Remove manifest ``.py`` files from a built wheel (release protection).

    Compiled ``.so`` artifacts are delivered by platform core wheels; the main
    harness release wheel must not ship readable source for those modules.

    When ``in_place`` is True, atomically replaces ``wheel_path`` with the
    stripped wheel (PEP 427 compliant filename preserved).
    """
    to_remove = frozenset(manifest_source_paths())
    if in_place:
        dest = wheel_path.with_suffix(".stripping.whl")
    else:
        dest = output_path or wheel_path

    with zipfile.ZipFile(wheel_path, "r") as src, zipfile.ZipFile(dest, "w") as dst:
        for info in src.infolist():
            if info.filename in to_remove:
                continue
            data = src.read(info.filename)
            dst.writestr(info, data)

    if in_place:
        dest.replace(wheel_path)
        return wheel_path
    return dest
