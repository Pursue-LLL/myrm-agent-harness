"""Generate distribution metadata from core_manifest.yaml (single SSOT).

[INPUT]
- harness_packaging.manifest::load_core_manifest (POS: YAML manifest loader)
- harness_packaging.integrity::{manifest_import_names, manifest_source_relpaths} (POS: Import/path mapping)
- harness_packaging.version::read_harness_version (POS: Harness version reader)

[OUTPUT]
- sync_distribution_metadata(): Regenerate _core_ip_manifest.py + pyproject compiled-core pins
- write_core_ip_manifest(): Write runtime manifest module only

[POS]
Build-time codegen for distribution SSOT. Invoked by scripts/sync_distribution_metadata.py and CI freshness tests.
"""

from __future__ import annotations

import re
from pathlib import Path

from harness_packaging.integrity import manifest_import_names, manifest_source_relpaths
from harness_packaging.manifest import load_core_manifest, repo_root
from harness_packaging.platforms import PUBLISH_PLATFORMS, platform_spec_for_key
from harness_packaging.version import read_harness_version

_GENERATED_HEADER = '''\
"""Core IP manifest (generated — do not edit).

Regenerate: uv run python scripts/sync_distribution_metadata.py
Source SSOT: harness_packaging/core_manifest.yaml
"""

from __future__ import annotations

'''

_COMPILED_CORE_BEGIN = "# BEGIN compiled-core (generated — do not edit)"
_COMPILED_CORE_END = "# END compiled-core"
_COMPILED_CORE_MUSL_BEGIN = "# BEGIN compiled-core-musl (generated — do not edit)"
_COMPILED_CORE_MUSL_END = "# END compiled-core-musl"


def generated_core_ip_manifest_path(root: Path | None = None) -> Path:
    """Return path to the generated runtime manifest module."""
    project_root = root or repo_root()
    return project_root / "src" / "myrm_agent_harness" / "_core_ip_manifest.py"


def _render_tuple(name: str, values: tuple[str, ...]) -> str:
    lines = [f"{name}: tuple[str, ...] = (\n"]
    for value in values:
        lines.append(f'    "{value}",\n')
    lines.append(")\n")
    return "".join(lines)


def render_core_ip_manifest_module(
    import_names: tuple[str, ...],
    source_relpaths: tuple[str, ...],
) -> str:
    """Render Python source for ``_core_ip_manifest.py``."""
    body = _render_tuple("CORE_IP_IMPORTS", import_names)
    body += _render_tuple("CORE_IP_SOURCE_RELPATHS", source_relpaths)
    return _GENERATED_HEADER + body


def write_core_ip_manifest(root: Path | None = None) -> Path:
    """Write ``_core_ip_manifest.py`` from the YAML manifest."""
    project_root = root or repo_root()
    path = generated_core_ip_manifest_path(project_root)
    path.write_text(
        render_core_ip_manifest_module(manifest_import_names(), manifest_source_relpaths()),
        encoding="utf-8",
    )
    return path


def _compiled_core_lines(version: str, *, musl: bool) -> list[str]:
    lines: list[str] = []
    for key in PUBLISH_PLATFORMS:
        spec = platform_spec_for_key(key)
        if spec.is_musl != musl:
            continue
        pkg = f"myrm-agent-harness-core-{key}=={version}"
        lines.append(f'  "{pkg}; {spec.pep508_marker}",')
    return lines


def render_compiled_core_sections(version: str) -> tuple[str, str]:
    """Render compiled-core and compiled-core-musl TOML blocks."""
    glibc_body = "\n".join(_compiled_core_lines(version, musl=False))
    musl_body = "\n".join(_compiled_core_lines(version, musl=True))
    glibc_section = f"compiled-core = [\n{glibc_body}\n]"
    musl_section = f"compiled-core-musl = [\n{musl_body}\n]" if musl_body else ""
    return glibc_section, musl_section


def _replace_marked_section(
    text: str,
    *,
    begin: str,
    end: str,
    replacement: str,
) -> str:
    pattern = re.compile(
        rf"{re.escape(begin)}.*?{re.escape(end)}",
        flags=re.DOTALL,
    )
    if not pattern.search(text):
        msg = f"Missing marker block {begin!r} .. {end!r} in pyproject.toml"
        raise ValueError(msg)
    return pattern.sub(f"{begin}\n{replacement}\n{end}", text, count=1)


def update_pyproject_compiled_core(root: Path | None = None) -> Path:
    """Sync compiled-core optional-deps version pins with project.version."""
    project_root = root or repo_root()
    pyproject_path = project_root / "pyproject.toml"
    version = read_harness_version(project_root)
    text = pyproject_path.read_text(encoding="utf-8")

    glibc_section, musl_section = render_compiled_core_sections(version)
    glibc_inner = glibc_section.removeprefix("compiled-core = [").removesuffix("]").strip()
    text = _replace_marked_section(
        text,
        begin=_COMPILED_CORE_BEGIN,
        end=_COMPILED_CORE_END,
        replacement=glibc_inner,
    )

    if musl_section:
        musl_inner = musl_section.removeprefix("compiled-core-musl = [").removesuffix("]").strip()
        text = _replace_marked_section(
            text,
            begin=_COMPILED_CORE_MUSL_BEGIN,
            end=_COMPILED_CORE_MUSL_END,
            replacement=musl_inner,
        )

    pyproject_path.write_text(text, encoding="utf-8")
    return pyproject_path


def sync_distribution_metadata(root: Path | None = None) -> tuple[Path, Path]:
    """Regenerate runtime manifest and pyproject compiled-core pins."""
    project_root = root or repo_root()
    load_core_manifest()
    manifest_path = write_core_ip_manifest(project_root)
    pyproject_path = update_pyproject_compiled_core(project_root)
    return manifest_path, pyproject_path
