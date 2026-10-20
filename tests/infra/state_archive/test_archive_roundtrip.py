"""Round-trip and hostile-input tests for ArchiveWriter / read_manifest / extract_payload."""

from __future__ import annotations

import sqlite3
import stat
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from myrm_agent_harness.infra.state_archive import (
    ArchiveErrorCode,
    ArchiveLimits,
    ArchiveManifest,
    ArchiveVerificationError,
    ArchiveWriteError,
    ArchiveWriter,
    EntryKind,
    ensure_free_space,
    extract_payload,
    read_manifest,
    snapshot_sqlite,
)
from myrm_agent_harness.infra.state_archive.models import (
    ARCHIVE_FORMAT,
    InsufficientSpaceError,
)


def _make_db(path: Path, rows: int = 20) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, data TEXT)")
    conn.executemany("INSERT INTO items (data) VALUES (?)", [(f"row-{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def _build_archive(tmp_path: Path) -> tuple[Path, ArchiveManifest]:
    src = tmp_path / "src"
    (src / "wiki").mkdir(parents=True)
    (src / "wiki" / "note.md").write_text("hello", encoding="utf-8")
    (src / "pic.png").write_bytes(b"\x89PNG" + b"0" * 64)
    _make_db(src / "data.db")
    dest = tmp_path / "out.zip"
    with ArchiveWriter(dest, producer={"app_version": "1.0"}, metadata={"note": "x"}) as writer:
        writer.add_file(src / "wiki" / "note.md", "wiki/note.md")
        writer.add_file(src / "pic.png", "pic.png")
        writer.add_sqlite(src / "data.db", "data.db")
        manifest = writer.finalize()
    return dest, manifest


def test_roundtrip_preserves_files_and_database(tmp_path: Path) -> None:
    archive, manifest = _build_archive(tmp_path)
    assert manifest.format == ARCHIVE_FORMAT
    assert {e.path for e in manifest.entries} == {"wiki/note.md", "pic.png", "data.db"}
    assert next(e for e in manifest.entries if e.path == "data.db").kind is EntryKind.SQLITE

    parsed = read_manifest(archive)
    assert parsed.producer == {"app_version": "1.0"}
    assert parsed.metadata["note"] == "x"

    out = tmp_path / "staging"
    written = extract_payload(archive, parsed, out)
    assert len(written) == 3
    assert (out / "wiki" / "note.md").read_text(encoding="utf-8") == "hello"
    conn = sqlite3.connect(str(out / "data.db"))
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone() == (20,)
    conn.close()
    assert not (out / "data.db-wal").exists()


def test_already_compressed_payload_is_stored(tmp_path: Path) -> None:
    archive, _ = _build_archive(tmp_path)
    with zipfile.ZipFile(archive) as zf:
        assert zf.getinfo("payload/pic.png").compress_type == zipfile.ZIP_STORED
        assert zf.getinfo("payload/wiki/note.md").compress_type == zipfile.ZIP_DEFLATED


def test_partial_file_is_removed_when_writer_aborts(tmp_path: Path) -> None:
    dest = tmp_path / "out.zip"
    with pytest.raises(RuntimeError), ArchiveWriter(dest, producer={}):
        raise RuntimeError("boom")
    assert not dest.exists()
    assert not dest.with_name("out.zip.partial").exists()


def test_vanished_source_is_recorded_as_skipped(tmp_path: Path) -> None:
    dest = tmp_path / "out.zip"
    with ArchiveWriter(dest, producer={}) as writer:
        assert writer.add_file(tmp_path / "missing.txt", "missing.txt") is None
        manifest = writer.finalize()
    assert manifest.metadata["skipped"] == [{"path": "missing.txt", "reason": "unreadable: FileNotFoundError"}]


class _FailingReader:
    """A source that yields one chunk and then fails, like a disk or volume that goes away mid-read."""

    def __init__(self) -> None:
        self._served = False

    def read(self, size: int = -1) -> bytes:
        if self._served:
            raise OSError("I/O error")
        self._served = True
        return b"abc"

    def __enter__(self) -> _FailingReader:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _patch_open(monkeypatch: pytest.MonkeyPatch, target: Path, opener: Callable[[], object]) -> None:
    real_open = Path.open

    def patched(self: Path, *args: object, **kwargs: object) -> object:
        return opener() if self == target else real_open(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", patched)


def _refuse_open() -> object:
    raise PermissionError("denied")


def test_read_failure_after_streaming_began_aborts_instead_of_publishing_a_torn_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "big.bin"
    src.write_bytes(b"x" * 100)
    _patch_open(monkeypatch, src, _FailingReader)
    dest = tmp_path / "out.zip"

    with pytest.raises(ArchiveWriteError), ArchiveWriter(dest, producer={}) as writer:
        writer.add_file(src, "big.bin")

    assert not dest.exists()
    assert not dest.with_name("out.zip.partial").exists()


def test_source_refused_before_streaming_is_skipped_and_the_archive_stays_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = tmp_path / "locked.bin"
    locked.write_bytes(b"x")
    fine = tmp_path / "fine.txt"
    fine.write_text("ok", encoding="utf-8")
    _patch_open(monkeypatch, locked, _refuse_open)
    dest = tmp_path / "out.zip"

    with ArchiveWriter(dest, producer={}) as writer:
        assert writer.add_file(locked, "locked.bin") is None
        writer.add_file(fine, "fine.txt")
        writer.finalize()

    manifest = read_manifest(dest)
    assert [entry.path for entry in manifest.entries] == ["fine.txt"]
    assert manifest.metadata["skipped"] == [{"path": "locked.bin", "reason": "unreadable: PermissionError"}]


def test_sqlite_prepare_failure_never_ships_the_unprepared_copy(tmp_path: Path) -> None:
    src = tmp_path / "data.db"
    _make_db(src)

    def _fail(_: Path) -> None:
        raise sqlite3.OperationalError("scrub failed")

    with ArchiveWriter(tmp_path / "out.zip", producer={}) as writer:
        assert writer.add_sqlite(src, "data.db", prepare=_fail) is None
        manifest = writer.finalize()
    assert manifest.entries == ()
    assert manifest.metadata["skipped"][0]["path"] == "data.db"


def test_duplicate_path_is_rejected(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("a", encoding="utf-8")
    with ArchiveWriter(tmp_path / "out.zip", producer={}) as writer:
        writer.add_file(f, "a.txt")
        with pytest.raises(ValueError, match="duplicate"):
            writer._write_member(f, "a.txt", EntryKind.FILE)


def test_compact_snapshot_drops_deleted_row_residue(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE secrets (v TEXT)")
    conn.execute("INSERT INTO secrets VALUES (?)", ("TOP-SECRET-MARKER" * 50,))
    conn.commit()
    conn.execute("DELETE FROM secrets")
    conn.commit()
    conn.close()
    assert b"TOP-SECRET-MARKER" in src.read_bytes()

    compact = tmp_path / "compact.db"
    snapshot_sqlite(src, compact, compact=True)
    assert b"TOP-SECRET-MARKER" not in compact.read_bytes()


def test_snapshot_refuses_to_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src)
    dst = tmp_path / "dst.db"
    dst.write_bytes(b"x")
    with pytest.raises(FileExistsError):
        snapshot_sqlite(src, dst)


def _rewrite_zip(archive: Path, mutate: Callable[[zipfile.ZipInfo, bytes], tuple[str, str | bytes] | None]) -> Path:
    out = archive.with_name("mutated.zip")
    with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            replacement = mutate(info, data)
            if replacement is None:
                continue
            zout.writestr(replacement[0], replacement[1])
    return out


def test_zip_slip_member_is_rejected(tmp_path: Path) -> None:
    archive, _ = _build_archive(tmp_path)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(evil, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info.filename, zin.read(info.filename))
        zout.writestr("payload/../../escape.txt", b"x")
    with pytest.raises(ArchiveVerificationError) as exc:
        read_manifest(evil)
    assert exc.value.code in {ArchiveErrorCode.UNSAFE_PATH, ArchiveErrorCode.CONTENT_MISMATCH}


def test_manifest_path_traversal_is_rejected(tmp_path: Path) -> None:
    archive, manifest = _build_archive(tmp_path)
    tampered = manifest.to_json().replace('"wiki/note.md"', '"../note.md"')
    out = _rewrite_zip(
        archive,
        lambda info, data: (info.filename, tampered if info.filename == "manifest.json" else data),
    )
    with pytest.raises(ArchiveVerificationError) as exc:
        read_manifest(out)
    assert exc.value.code is ArchiveErrorCode.UNSAFE_PATH


def test_symlink_member_is_rejected(tmp_path: Path) -> None:
    archive, _ = _build_archive(tmp_path)
    out = tmp_path / "link.zip"
    with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info.filename, zin.read(info.filename))
        link = zipfile.ZipInfo("payload/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zout.writestr(link, "/etc/passwd")
    with pytest.raises(ArchiveVerificationError) as exc:
        read_manifest(out)
    assert exc.value.code is ArchiveErrorCode.SYMLINK


def test_tampered_payload_fails_hash_and_leaves_no_staging(tmp_path: Path) -> None:
    archive, manifest = _build_archive(tmp_path)
    out = _rewrite_zip(
        archive,
        lambda info, data: (info.filename, b"HELLO" if info.filename == "payload/wiki/note.md" else data),
    )
    parsed = read_manifest(out)
    staging = tmp_path / "staging"
    with pytest.raises(ArchiveVerificationError) as exc:
        extract_payload(out, parsed, staging)
    assert exc.value.code is ArchiveErrorCode.HASH_MISMATCH
    assert not staging.exists()
    assert manifest.entries


def test_undeclared_member_is_rejected(tmp_path: Path) -> None:
    archive, _ = _build_archive(tmp_path)
    out = tmp_path / "extra.zip"
    with zipfile.ZipFile(archive) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info.filename, zin.read(info.filename))
        zout.writestr("payload/sneaky.bin", b"x")
    with pytest.raises(ArchiveVerificationError) as exc:
        read_manifest(out)
    assert exc.value.code is ArchiveErrorCode.CONTENT_MISMATCH


def test_missing_manifest_and_non_zip(tmp_path: Path) -> None:
    only_payload = tmp_path / "nomanifest.zip"
    with zipfile.ZipFile(only_payload, "w") as zout:
        zout.writestr("payload/a.txt", b"a")
    with pytest.raises(ArchiveVerificationError) as exc:
        read_manifest(only_payload)
    assert exc.value.code is ArchiveErrorCode.MISSING_MANIFEST

    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(ArchiveVerificationError) as exc2:
        read_manifest(junk)
    assert exc2.value.code is ArchiveErrorCode.NOT_A_ZIP


def test_unsupported_future_format_version_is_rejected(tmp_path: Path) -> None:
    archive, manifest = _build_archive(tmp_path)
    tampered = manifest.to_json().replace('"format_version": 1', '"format_version": 99')
    out = _rewrite_zip(
        archive,
        lambda info, data: (info.filename, tampered if info.filename == "manifest.json" else data),
    )
    with pytest.raises(ArchiveVerificationError) as exc:
        read_manifest(out)
    assert exc.value.code is ArchiveErrorCode.UNSUPPORTED_FORMAT


def test_limits_reject_oversized_and_overpopulated_archives(tmp_path: Path) -> None:
    archive, manifest = _build_archive(tmp_path)
    with pytest.raises(ArchiveVerificationError) as too_large:
        read_manifest(archive, ArchiveLimits(max_total_bytes=manifest.total_bytes - 1))
    assert too_large.value.code is ArchiveErrorCode.TOO_LARGE
    with pytest.raises(ArchiveVerificationError) as too_many:
        read_manifest(archive, ArchiveLimits(max_entries=1))
    assert too_many.value.code is ArchiveErrorCode.TOO_MANY_ENTRIES


def test_select_filter_extracts_only_chosen_entries(tmp_path: Path) -> None:
    archive, manifest = _build_archive(tmp_path)
    out = tmp_path / "staging"
    written = extract_payload(archive, manifest, out, select=lambda e: e.path.startswith("wiki/"))
    assert [e.path for e in written] == ["wiki/note.md"]
    assert not (out / "data.db").exists()


def test_ensure_free_space(tmp_path: Path) -> None:
    ensure_free_space(tmp_path / "not" / "yet" / "created", 1)
    with pytest.raises(InsufficientSpaceError):
        ensure_free_space(tmp_path, 1 << 62)
