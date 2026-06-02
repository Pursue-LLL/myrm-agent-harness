"""Tests for zip_extract.py — safe ZIP extraction with security hardening."""

import io
import zipfile

import pytest

from myrm_agent_harness.backends.skills.scanning.zip_extract import safe_extract_zip


def _make_zip(files: dict[str, bytes], *, symlinks: list[str] | None = None) -> bytes:
    """Helper to create a ZIP in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
        if symlinks:
            for sym_path in symlinks:
                info = zipfile.ZipInfo(sym_path)
                info.external_attr = (0o120000 << 16) | 0o777
                zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


class TestSafeExtractZip:
    """Tests for safe_extract_zip."""

    def test_basic_extraction(self):
        zip_bytes = _make_zip({"top/hello.txt": b"world", "top/sub/file.py": b"print(1)"})
        result = safe_extract_zip(zip_bytes)
        assert "hello.txt" in result
        assert result["hello.txt"] == b"world"
        assert "sub/file.py" in result
        assert result["sub/file.py"] == b"print(1)"

    def test_strip_top_dir(self):
        zip_bytes = _make_zip({"myskill/SKILL.md": b"# Skill"})
        result = safe_extract_zip(zip_bytes, strip_top_dir=True)
        assert "SKILL.md" in result

    def test_no_strip_top_dir(self):
        zip_bytes = _make_zip({"myskill/SKILL.md": b"# Skill"})
        result = safe_extract_zip(zip_bytes, strip_top_dir=False)
        assert "myskill/SKILL.md" in result

    def test_skips_directories(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("top/", "")
            zf.writestr("top/file.txt", "content")
        result = safe_extract_zip(buf.getvalue())
        assert len(result) == 1
        assert "file.txt" in result

    def test_rejects_zip_bomb(self):
        large_content = b"\x00" * (1024 * 1024)
        zip_bytes = _make_zip({"top/bomb.bin": large_content})
        with pytest.raises(ValueError, match="Zip Bomb"):
            safe_extract_zip(zip_bytes, max_compression_ratio=2)

    def test_rejects_size_limit(self):
        content = b"x" * 1000
        zip_bytes = _make_zip({"top/big.txt": content})
        with pytest.raises(ValueError, match="exceeds"):
            safe_extract_zip(zip_bytes, max_total_bytes=100)

    def test_skips_symlinks(self):
        zip_bytes = _make_zip(
            {"top/safe.txt": b"safe"},
            symlinks=["top/evil_link"],
        )
        result = safe_extract_zip(zip_bytes)
        assert "safe.txt" in result
        assert "evil_link" not in result

    def test_skips_path_traversal(self):
        zip_bytes = _make_zip(
            {
                "top/safe.txt": b"safe",
                "top/../../../etc/passwd": b"root:x:0:0",
            }
        )
        result = safe_extract_zip(zip_bytes)
        assert "safe.txt" in result
        assert not any(".." in k for k in result)

    def test_forbidden_check_callback(self):
        zip_bytes = _make_zip(
            {
                "top/keep.txt": b"keep",
                "top/drop.exe": b"bad",
            }
        )
        result = safe_extract_zip(
            zip_bytes,
            forbidden_check=lambda p: p.endswith(".exe"),
        )
        assert "keep.txt" in result
        assert "drop.exe" not in result

    def test_empty_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        result = safe_extract_zip(buf.getvalue())
        assert result == {}

    def test_default_limits_accept_normal_zip(self):
        content = b"normal content " * 100
        zip_bytes = _make_zip({"top/file.txt": content})
        result = safe_extract_zip(zip_bytes)
        assert "file.txt" in result
