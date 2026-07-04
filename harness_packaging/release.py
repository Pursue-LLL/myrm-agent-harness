"""Release wheel utilities — strip core IP source from distributable wheels."""

from __future__ import annotations

import base64
import hashlib
import subprocess
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


def _sha256_record_digest(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _build_record_line(path: str, data: bytes) -> str:
    return f"{path},sha256={_sha256_record_digest(data)},{len(data)}"


def _find_record_path(filenames: tuple[str, ...]) -> str:
    for name in filenames:
        if name.endswith(".dist-info/RECORD"):
            return name
    msg = "Wheel is missing .dist-info/RECORD"
    raise RuntimeError(msg)


def _build_wheel_record(record_path: str, entries: list[tuple[str, bytes]]) -> bytes:
    lines = [_build_record_line(path, data) for path, data in sorted(entries, key=lambda item: item[0])]
    lines.append(f"{record_path},,")
    return ("\n".join(lines) + "\n").encode("utf-8")


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

    with zipfile.ZipFile(wheel_path, "r") as src:
        record_path = _find_record_path(tuple(src.namelist()))
        kept_entries: list[tuple[str, bytes]] = []
        for info in src.infolist():
            if info.filename in to_remove or info.filename == record_path:
                continue
            kept_entries.append((info.filename, src.read(info.filename)))

    kept_entries.append((record_path, _build_wheel_record(record_path, kept_entries)))

    with zipfile.ZipFile(dest, "w") as dst:
        for path, data in kept_entries:
            dst.writestr(path, data)

    if in_place:
        dest.replace(wheel_path)
        return wheel_path
    return dest


def build_harness_source_wheel(dist_dir: Path) -> Path:
    """Build the main harness wheel with ``uv build`` and return the produced path."""
    dist_dir.mkdir(parents=True, exist_ok=True)
    root = repo_root()
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        check=True,
        cwd=root,
    )
    wheels = sorted(
        dist_dir.glob("myrm_agent_harness-*.whl"),
        key=lambda path: path.stat().st_mtime,
    )
    if not wheels:
        msg = f"No harness wheel produced in {dist_dir}"
        raise RuntimeError(msg)
    return wheels[-1]


def finalize_stripped_release_wheel(
    wheel_path: Path,
    *,
    in_place: bool = True,
) -> Path:
    """Strip manifest ``.py`` from a release wheel and verify artifact rules."""
    from harness_packaging.integrity import DistributionWheelRole, verify_distribution_wheel_artifact

    stripped = strip_manifest_sources_from_wheel(wheel_path, in_place=in_place)
    verify_distribution_wheel_artifact(stripped, role=DistributionWheelRole.RELEASE)
    return stripped
