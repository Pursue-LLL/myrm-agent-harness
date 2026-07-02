"""Map manifest module files to import names, source paths, and drift-gate checks."""

from __future__ import annotations

import zipfile
from enum import StrEnum
from pathlib import Path

from harness_packaging.manifest import load_core_manifest, repo_root
from harness_packaging.release import manifest_source_paths


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
    "toolkits/memory/proactive",
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


class DistributionWheelRole(StrEnum):
    """Built wheel kind for distribution artifact verification."""

    RELEASE = "release"
    CORE = "core"


class DistributionWheelArtifactError(ValueError):
    """Raised when a built wheel violates release or core artifact rules."""


_FORBIDDEN_DEBUG_SUFFIXES: tuple[str, ...] = (".map", ".c.src")


def _manifest_compiled_prefix(manifest_py: str) -> str:
    """Return the wheel entry prefix for a manifest module's Nuitka artifact."""
    if not manifest_py.endswith(".py"):
        msg = f"Expected manifest path ending in .py, got: {manifest_py!r}"
        raise ValueError(msg)
    if manifest_py.endswith("/__init__.py"):
        parent_dir = manifest_py[: -len("/__init__.py")]
        stem = parent_dir.rsplit("/", 1)[-1]
        return f"{parent_dir}/{stem}."
    return f"{manifest_py[:-3]}."


def manifest_compiled_artifact_prefix(manifest_wheel_py: str) -> str:
    """Return the wheel zip entry prefix for a manifest module's compiled artifact."""
    return _manifest_compiled_prefix(manifest_wheel_py)


def _wheel_zip_entries(wheel_path: Path) -> tuple[str, ...]:
    with zipfile.ZipFile(wheel_path, "r") as zf:
        return tuple(zf.namelist())


def _forbidden_debug_entries(entries: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        name
        for name in entries
        if name.endswith(_FORBIDDEN_DEBUG_SUFFIXES)
    )


def _has_compiled_artifact(entries: tuple[str, ...], manifest_py: str) -> bool:
    prefix = _manifest_compiled_prefix(manifest_py)
    return any(
        name.startswith(prefix) and (name.endswith(".so") or name.endswith(".pyd"))
        for name in entries
    )


def distribution_wheel_artifact_violations(
    wheel_path: Path,
    *,
    role: DistributionWheelRole,
) -> tuple[str, ...]:
    """Return human-readable violations for a release or platform core wheel."""
    if not wheel_path.is_file():
        return (f"Wheel file not found: {wheel_path}",)

    try:
        entries = _wheel_zip_entries(wheel_path)
    except zipfile.BadZipFile:
        return (f"Invalid wheel zip: {wheel_path.name}",)

    entry_set = frozenset(entries)
    violations: list[str] = []

    manifest_paths = manifest_source_paths()
    leaked = [path for path in manifest_paths if path in entry_set]
    if leaked:
        preview = ", ".join(leaked[:3])
        suffix = f" (+{len(leaked) - 3} more)" if len(leaked) > 3 else ""
        violations.append(f"Manifest .py source must not ship in wheel: {preview}{suffix}")

    debug_entries = _forbidden_debug_entries(entries)
    if debug_entries:
        preview = ", ".join(debug_entries[:3])
        suffix = f" (+{len(debug_entries) - 3} more)" if len(debug_entries) > 3 else ""
        violations.append(f"Debug mapping artifacts must not ship in wheel: {preview}{suffix}")

    if role is DistributionWheelRole.CORE:
        missing_compiled = [
            path for path in manifest_paths if not _has_compiled_artifact(entries, path)
        ]
        if missing_compiled:
            preview = ", ".join(missing_compiled[:3])
            suffix = f" (+{len(missing_compiled) - 3} more)" if len(missing_compiled) > 3 else ""
            violations.append(f"Missing Nuitka .so/.pyd for manifest modules: {preview}{suffix}")

    return tuple(violations)


def verify_distribution_wheel_artifact(
    wheel_path: Path,
    *,
    role: DistributionWheelRole,
) -> None:
    """Fail closed when a built wheel violates distribution artifact rules."""
    violations = distribution_wheel_artifact_violations(wheel_path, role=role)
    if not violations:
        return
    joined = "\n  - ".join(violations)
    msg = (
        f"Distribution wheel artifact violations ({role.value}) in {wheel_path.name}:\n"
        f"  - {joined}"
    )
    raise DistributionWheelArtifactError(msg)
