"""Map manifest module files to import names, source paths, and drift-gate checks."""

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


DISTRIBUTION_PUBLIC_MARKER = "@distribution-public"

_MARKER_SCAN_BYTES = 4096

# Sibling zones: new subdirectories/files outside known public trees need manifest or marker.
_PARENT_WATCH_ZONES: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "agent/skills/",
        "agent/skills/evolution",
        frozenset(
            {
                "curator",
                "discovery",
                "history",
                "mcp",
                "optimization",
                "packaging",
                "runtime",
                "security",
                "sync",
            }
        ),
    ),
    (
        "agent/context_management/",
        "agent/context_management/pipeline",
        frozenset({"archive_checkpoint", "infra", "strategies", "tracking"}),
    ),
)

_MEMORY_MANIFEST_PREFIXES: tuple[str, ...] = (
    "toolkits/memory/strategies",
    "toolkits/memory/cognitive",
)

_MEMORY_PUBLIC_SUBDIRS: frozenset[str] = frozenset(
    {
        "graph",
        "integration",
        "protocols",
        "relational",
        "_manager",
        "conversation_search",
        "_internal",
    }
)


def _file_has_public_marker(module_file: Path) -> bool:
    head = module_file.read_bytes()[:_MARKER_SCAN_BYTES].decode("utf-8", errors="ignore")
    return DISTRIBUTION_PUBLIC_MARKER in head


def _is_under_manifest_dir(rel_posix: str, manifest_dir: str) -> bool:
    return rel_posix == manifest_dir or rel_posix.startswith(f"{manifest_dir}/")


def manifest_watch_violations() -> tuple[str, ...]:
    """Return ``myrm_agent_harness/``-relative paths missing manifest coverage or public marker."""
    manifest = load_core_manifest()
    manifest_files = {path.resolve() for path in manifest.module_paths}
    src_root = repo_root() / "src" / "myrm_agent_harness"
    violations: list[str] = []

    for parent_prefix, manifest_dir_prefix, public_subdirs in _PARENT_WATCH_ZONES:
        zone_root = src_root / parent_prefix
        if not zone_root.is_dir():
            continue
        for module_file in sorted(zone_root.rglob("*.py")):
            rel = module_file.relative_to(src_root).as_posix()
            if _is_under_manifest_dir(rel, manifest_dir_prefix):
                continue
            rel_to_parent = module_file.relative_to(zone_root)
            if len(rel_to_parent.parts) == 1:
                continue
            if rel_to_parent.parts[0] in public_subdirs:
                continue
            if module_file.resolve() in manifest_files:
                continue
            if _file_has_public_marker(module_file):
                continue
            violations.append(rel)

    memory_root = src_root / "toolkits/memory"
    if memory_root.is_dir():
        for module_file in sorted(memory_root.rglob("*.py")):
            rel = module_file.relative_to(src_root).as_posix()
            if any(_is_under_manifest_dir(rel, prefix) for prefix in _MEMORY_MANIFEST_PREFIXES):
                continue
            rel_to_memory = module_file.relative_to(memory_root)
            if len(rel_to_memory.parts) == 1:
                continue
            if rel_to_memory.parts[0] in _MEMORY_PUBLIC_SUBDIRS:
                continue
            if module_file.resolve() in manifest_files:
                continue
            if _file_has_public_marker(module_file):
                continue
            violations.append(rel)

    return tuple(violations)
