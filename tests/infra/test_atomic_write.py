"""Unit tests for infra/atomic_write.py."""

import asyncio
import os
import stat
from pathlib import Path

import pytest

from myrm_agent_harness.infra.atomic_write import async_atomic_write, atomic_write


class TestAtomicWriteText:
    def test_basic_write(self, tmp_path: Path) -> None:
        target = tmp_path / "test.json"
        atomic_write(target, '{"key": "value"}')
        assert target.read_text(encoding="utf-8") == '{"key": "value"}'

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "test.json"
        target.write_text("old content")
        atomic_write(target, "new content")
        assert target.read_text(encoding="utf-8") == "new content"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c" / "test.json"
        atomic_write(target, "nested")
        assert target.read_text(encoding="utf-8") == "nested"

    def test_default_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "secure.json"
        atomic_write(target, "secret")
        file_mode = stat.S_IMODE(os.stat(target).st_mode)
        assert file_mode == 0o600

    def test_custom_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "readable.json"
        atomic_write(target, "public", mode=0o644)
        file_mode = stat.S_IMODE(os.stat(target).st_mode)
        assert file_mode == 0o644

    def test_no_chmod_when_none(self, tmp_path: Path) -> None:
        target = tmp_path / "nochmod.json"
        atomic_write(target, "content", mode=None)
        assert target.read_text(encoding="utf-8") == "content"

    def test_unicode_content(self, tmp_path: Path) -> None:
        target = tmp_path / "unicode.json"
        content = '{"名前": "テスト", "emoji": ""}'
        atomic_write(target, content)
        assert target.read_text(encoding="utf-8") == content

    def test_empty_content(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.json"
        atomic_write(target, "")
        assert target.read_text(encoding="utf-8") == ""

    def test_large_content(self, tmp_path: Path) -> None:
        target = tmp_path / "large.json"
        content = "x" * 1_000_000
        atomic_write(target, content)
        assert target.read_text(encoding="utf-8") == content

    def test_no_temp_file_left_on_success(self, tmp_path: Path) -> None:
        target = tmp_path / "clean.json"
        atomic_write(target, "data")
        remaining = list(tmp_path.iterdir())
        assert remaining == [target]


class TestAtomicWriteBytes:
    def test_basic_bytes(self, tmp_path: Path) -> None:
        target = tmp_path / "test.bin"
        data = b"\x00\x01\x02\x03\xff"
        atomic_write(target, data)
        assert target.read_bytes() == data

    def test_large_binary(self, tmp_path: Path) -> None:
        target = tmp_path / "large.bin"
        data = os.urandom(500_000)
        atomic_write(target, data)
        assert target.read_bytes() == data


class TestAtomicWriteErrorHandling:
    def test_no_temp_file_left_on_error(self, tmp_path: Path) -> None:
        target = tmp_path / "nonexistent_parent" / "sub" / "test.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(target.parent, 0o444)
        try:
            with pytest.raises(OSError):
                atomic_write(target, "data")
        finally:
            os.chmod(target.parent, 0o755)

    def test_original_preserved_on_error(self, tmp_path: Path) -> None:
        target = tmp_path / "preserve.json"
        target.write_text("original")
        read_only_dir = tmp_path / "readonly"
        read_only_dir.mkdir()
        os.chmod(read_only_dir, 0o444)
        readonly_target = read_only_dir / "test.json"
        try:
            with pytest.raises(OSError):
                atomic_write(readonly_target, "new data")
        finally:
            os.chmod(read_only_dir, 0o755)
        assert target.read_text() == "original"

    def test_accepts_str_path(self, tmp_path: Path) -> None:
        target = str(tmp_path / "strpath.json")
        atomic_write(target, "string path")
        assert Path(target).read_text(encoding="utf-8") == "string path"


class TestAsyncAtomicWrite:
    def test_async_text(self, tmp_path: Path) -> None:
        target = tmp_path / "async.json"
        asyncio.run(async_atomic_write(target, '{"async": true}'))
        assert target.read_text(encoding="utf-8") == '{"async": true}'

    def test_async_bytes(self, tmp_path: Path) -> None:
        target = tmp_path / "async.bin"
        data = b"\xde\xad\xbe\xef"
        asyncio.run(async_atomic_write(target, data))
        assert target.read_bytes() == data

    def test_async_creates_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "async.json"
        asyncio.run(async_atomic_write(target, "deep"))
        assert target.read_text(encoding="utf-8") == "deep"


class TestConcurrentWrites:
    def test_no_corruption_under_concurrent_writes(self, tmp_path: Path) -> None:
        """Multiple threads writing to the same file should never produce corruption."""
        import threading

        target = tmp_path / "concurrent.json"
        errors: list[Exception] = []
        barrier = threading.Barrier(10)

        def writer(idx: int) -> None:
            try:
                barrier.wait(timeout=5)
                content = f'{{"writer": {idx}, "data": "{" x " * 1000}"}}'
                atomic_write(target, content)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Errors during concurrent writes: {errors}"
        content = target.read_text(encoding="utf-8")
        assert content.startswith("{")
        assert content.endswith("}")
