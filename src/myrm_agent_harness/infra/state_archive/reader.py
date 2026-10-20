"""Untrusted-archive inspection and verified extraction.

[INPUT]
- state_archive.models (POS: manifest, limits, typed errors)

[OUTPUT]
- read_manifest: Validate structure/safety and return the manifest without extracting payload.
- extract_payload: Stream selected entries into a directory, verifying size and SHA-256 on the way.
- ensure_free_space: Preflight disk check raising ``InsufficientSpaceError``.

[POS]
Import half of ``infra/state_archive``. Every member is treated as hostile: names are
validated before anything is written, extraction never exceeds the declared size, and a
failed extraction leaves no partial target behind.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from .models import (
    ARCHIVE_FORMAT,
    ARCHIVE_FORMAT_VERSION,
    DEFAULT_MAX_MANIFEST_BYTES,
    MANIFEST_NAME,
    PAYLOAD_PREFIX,
    ArchiveEntry,
    ArchiveErrorCode,
    ArchiveLimits,
    ArchiveManifest,
    ArchiveVerificationError,
    InsufficientSpaceError,
)

_COPY_BUFFER = 1 << 20


def ensure_free_space(path: Path, required_bytes: int) -> None:
    """Raise ``InsufficientSpaceError`` unless the volume holding ``path`` has the space."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if free < required_bytes:
        raise InsufficientSpaceError(required_bytes, free)


def read_manifest(archive: Path, limits: ArchiveLimits | None = None) -> ArchiveManifest:
    """Validate ``archive`` structurally and return its manifest. No payload is extracted."""
    bounds = limits or ArchiveLimits()
    try:
        with zipfile.ZipFile(archive) as zf:
            infos = {info.filename: info for info in zf.infolist() if not info.is_dir()}
            _check_member_names(zf.infolist())
            manifest_info = infos.get(MANIFEST_NAME)
            if manifest_info is None:
                raise ArchiveVerificationError(ArchiveErrorCode.MISSING_MANIFEST, "Archive has no manifest")
            if manifest_info.file_size > DEFAULT_MAX_MANIFEST_BYTES:
                raise ArchiveVerificationError(ArchiveErrorCode.BAD_MANIFEST, "Manifest is unreasonably large")
            manifest = ArchiveManifest.from_json(zf.read(MANIFEST_NAME))
            _check_manifest(manifest, infos, bounds)
            return manifest
    except zipfile.BadZipFile as exc:
        raise ArchiveVerificationError(ArchiveErrorCode.NOT_A_ZIP, "File is not a valid zip archive") from exc


def extract_payload(
    archive: Path,
    manifest: ArchiveManifest,
    dest: Path,
    *,
    select: Callable[[ArchiveEntry], bool] | None = None,
) -> tuple[ArchiveEntry, ...]:
    """Extract selected entries into ``dest`` (created if needed); return what was written.

    Each file is written to a temp name, verified against the manifest, then renamed. Any
    failure removes ``dest`` entirely so a half-extracted tree can never be promoted.
    """
    written: list[ArchiveEntry] = []
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    try:
        with zipfile.ZipFile(archive) as zf:
            for entry in manifest.entries:
                if select is not None and not select(entry):
                    continue
                target = _safe_target(root, entry.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                _extract_entry(zf, entry, target)
                written.append(entry)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return tuple(written)


def _extract_entry(zf: zipfile.ZipFile, entry: ArchiveEntry, target: Path) -> None:
    partial = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    size = 0
    with zf.open(PAYLOAD_PREFIX + entry.path) as reader, partial.open("wb") as writer:
        while chunk := reader.read(_COPY_BUFFER):
            size += len(chunk)
            if size > entry.size_bytes:
                raise ArchiveVerificationError(
                    ArchiveErrorCode.SIZE_MISMATCH, f"Entry exceeds its declared size: {entry.path}"
                )
            digest.update(chunk)
            writer.write(chunk)
    if size != entry.size_bytes:
        raise ArchiveVerificationError(ArchiveErrorCode.SIZE_MISMATCH, f"Entry is truncated: {entry.path}")
    if digest.hexdigest() != entry.sha256:
        raise ArchiveVerificationError(ArchiveErrorCode.HASH_MISMATCH, f"Checksum mismatch: {entry.path}")
    partial.replace(target)


def _check_member_names(infos: list[zipfile.ZipInfo]) -> None:
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        if name in seen:
            raise ArchiveVerificationError(ArchiveErrorCode.DUPLICATE_ENTRY, f"Duplicate member: {name}")
        seen.add(name)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ArchiveVerificationError(ArchiveErrorCode.SYMLINK, f"Symlink member rejected: {name}")
        if name != MANIFEST_NAME and not name.startswith(PAYLOAD_PREFIX):
            raise ArchiveVerificationError(ArchiveErrorCode.UNSAFE_PATH, f"Unexpected member: {name}")


def _check_manifest(manifest: ArchiveManifest, infos: dict[str, zipfile.ZipInfo], limits: ArchiveLimits) -> None:
    if manifest.format != ARCHIVE_FORMAT or manifest.format_version > ARCHIVE_FORMAT_VERSION:
        raise ArchiveVerificationError(
            ArchiveErrorCode.UNSUPPORTED_FORMAT,
            f"Unsupported archive format {manifest.format} v{manifest.format_version}",
        )
    if len(manifest.entries) > limits.max_entries:
        raise ArchiveVerificationError(ArchiveErrorCode.TOO_MANY_ENTRIES, "Archive has too many entries")
    if limits.max_total_bytes is not None and manifest.total_bytes > limits.max_total_bytes:
        raise ArchiveVerificationError(ArchiveErrorCode.TOO_LARGE, "Archive payload exceeds the allowed size")
    declared = set()
    for entry in manifest.entries:
        _validate_relative(entry.path)
        member = infos.get(PAYLOAD_PREFIX + entry.path)
        if member is None or member.file_size != entry.size_bytes:
            raise ArchiveVerificationError(
                ArchiveErrorCode.CONTENT_MISMATCH, f"Manifest and archive disagree on: {entry.path}"
            )
        declared.add(PAYLOAD_PREFIX + entry.path)
    extras = {name for name in infos if name.startswith(PAYLOAD_PREFIX)} - declared
    if extras:
        raise ArchiveVerificationError(ArchiveErrorCode.CONTENT_MISMATCH, "Archive contains undeclared members")


def _validate_relative(path: str) -> PurePosixPath:
    pure = PurePosixPath(path)
    if (
        not path
        or "\\" in path
        or "\x00" in path
        or pure.is_absolute()
        or any(part in ("..", ".", "") for part in path.split("/"))
        or (pure.parts and ":" in pure.parts[0])
    ):
        raise ArchiveVerificationError(ArchiveErrorCode.UNSAFE_PATH, f"Unsafe archive path: {path!r}")
    return pure


def _safe_target(root: Path, rel_path: str) -> Path:
    target = (root / _validate_relative(rel_path)).resolve()
    if root != target and root not in target.parents:
        raise ArchiveVerificationError(ArchiveErrorCode.UNSAFE_PATH, f"Path escapes extraction root: {rel_path}")
    return target
