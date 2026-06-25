"""Map manifest module files to import names and source-relative paths."""

from __future__ import annotations

from pathlib import Path

from harness_packaging.manifest import load_core_manifest, repo_root


def module_file_to_import_name(module_file: Path, src_root: Path) -> str:
    """Return the dotted import path for a module file under ``myrm_agent_harness``."""
    rel = module_file.relative_to(src_root)
    if rel.name == "__init__.py":
        parts = rel.parent.parts
    else:
        parts = rel.with_suffix("").parts
    return f"myrm_agent_harness.{'.'.join(parts)}"


def module_file_to_source_relpath(module_file: Path, src_root: Path) -> str:
    """Return wheel/source path relative to ``myrm_agent_harness/``."""
    rel = module_file.relative_to(src_root)
    return rel.as_posix()


def manifest_import_names() -> tuple[str, ...]:
    """Return deduplicated import paths for manifest modules."""
    manifest = load_core_manifest()
    src_root = repo_root() / "src" / "myrm_agent_harness"
    seen: dict[str, None] = {}
    for module_file in manifest.module_paths:
        seen[module_file_to_import_name(module_file, src_root)] = None
    return tuple(seen)


def manifest_source_relpaths() -> tuple[str, ...]:
    """Return ``myrm_agent_harness/``-relative ``.py`` paths for manifest modules."""
    manifest = load_core_manifest()
    src_root = repo_root() / "src" / "myrm_agent_harness"
    return tuple(
        module_file_to_source_relpath(module_file, src_root) for module_file in manifest.module_paths
    )


def verify_manifest_imports() -> None:
    """Import every manifest module (post-install CI/Docker verification)."""
    import importlib

    for import_name in manifest_import_names():
        importlib.import_module(import_name)
