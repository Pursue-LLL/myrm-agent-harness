"""Portable full-vault ZIP archive for WikiStructure.

[INPUT]
myrm_agent_harness.toolkits.wiki.core.structure::WikiStructure

[OUTPUT]
build_vault_archive_zip: ZIP bytes for raw + wiki tree (excludes internal caches)

[POS]
Framework-level vault file export. Server adds Obsidian-specific presets separately.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

EXPORT_MANIFEST_VERSION = 2

_EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".venv",
        ".env",
        "__MACOSX",
        ".obsidian",
        ".idea",
        ".vscode",
    }
)

_EXCLUDED_FILE_NAMES: frozenset[str] = frozenset(
    {
        ".metadata.json",
        ".DS_Store",
    }
)


def _vault_relative(path: Path, vault_base: Path) -> str:
    return path.relative_to(vault_base).as_posix()


def _should_include_vault_file(path: Path, vault_base: Path) -> bool:
    relative = path.relative_to(vault_base)
    if any(part in _EXCLUDED_DIR_NAMES for part in relative.parts):
        return False
    if path.name in _EXCLUDED_FILE_NAMES:
        return False
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return False
    return True


def iter_vault_files(structure: WikiStructure) -> list[tuple[Path, str]]:
    """Return sorted (absolute_path, vault_relative_path) pairs for export."""
    vault_base = structure.base_dir
    if not vault_base.is_dir():
        return []

    pairs: list[tuple[Path, str]] = []
    for file_path in sorted(vault_base.rglob("*")):
        if not file_path.is_file():
            continue
        if not _should_include_vault_file(file_path, vault_base):
            continue
        pairs.append((file_path, _vault_relative(file_path, vault_base)))
    return pairs


def build_vault_archive_zip(
    structure: WikiStructure,
    agent_id: str | None = None,
    *,
    extra_entries: dict[str, str | bytes] | None = None,
) -> io.BytesIO:
    """Build a portable zip of the full agent wiki vault directory."""
    vault_base = structure.base_dir
    memory_file = io.BytesIO()
    included_paths: list[str] = []

    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path, arcname in iter_vault_files(structure):
            zf.write(file_path, arcname)
            included_paths.append(arcname)

        if extra_entries:
            for arcname, payload in extra_entries.items():
                if isinstance(payload, str):
                    zf.writestr(arcname, payload)
                else:
                    zf.writestr(arcname, payload)
                included_paths.append(arcname)

        manifest = {
            "version": EXPORT_MANIFEST_VERSION,
            "exported_at": datetime.now(UTC).isoformat(),
            "agent_id": agent_id,
            "vault_root": "Open this folder as an Obsidian vault (File → Open folder as vault).",
            "files": sorted(included_paths),
            "concepts_count": len([path for path in included_paths if path.startswith("wiki/concepts/")]),
            "raw_count": len([path for path in included_paths if path.startswith("raw/")]),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    memory_file.seek(0)
    return memory_file
