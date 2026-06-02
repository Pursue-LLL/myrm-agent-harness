"""Runtime integrity checks for harness distribution (build/CI helpers)."""

from __future__ import annotations

import importlib

from harness_packaging.manifest import load_core_manifest, repo_root


def manifest_import_names() -> tuple[str, ...]:
    """Return dotted import paths for manifest modules (from core_manifest.yaml)."""
    manifest = load_core_manifest()
    src_root = repo_root() / "src" / "myrm_agent_harness"
    names: list[str] = []
    for module_file in manifest.module_paths:
        rel = module_file.relative_to(src_root)
        parts = rel.with_suffix("").parts
        names.append(f"myrm_agent_harness.{'.'.join(parts)}")
    return tuple(names)


def verify_manifest_imports() -> None:
    """Import every manifest module (post-install CI/Docker verification)."""
    for import_name in manifest_import_names():
        importlib.import_module(import_name)
