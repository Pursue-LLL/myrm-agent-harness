"""Tests for archive_sanitizer: Zip slip / tar extraction defense."""

from myrm_agent_harness.toolkits.code_execution.security.archive_sanitizer import (
    _is_tar_extract,
    sanitize_archive_command,
)


class TestTarDetection:
    def test_tar_extract_short_flag(self):
        assert _is_tar_extract("tar xf archive.tar.gz")

    def test_tar_extract_long_flag(self):
        assert _is_tar_extract("tar --extract -f archive.tar.gz")

    def test_tar_extract_combined_flags(self):
        assert _is_tar_extract("tar xzf archive.tar.gz")

    def test_tar_create_not_detected(self):
        assert not _is_tar_extract("tar cf archive.tar .")

    def test_tar_list_not_detected(self):
        assert not _is_tar_extract("tar tf archive.tar.gz")

    def test_no_tar(self):
        assert not _is_tar_extract("ls -la")


class TestSanitizeTar:
    def test_injects_safe_flags(self):
        result = sanitize_archive_command("tar xf archive.tar.gz")
        assert "--no-same-permissions" in result
        assert "--no-same-owner" in result

    def test_skips_already_safe(self):
        cmd = "tar xf archive.tar.gz --no-same-permissions --no-same-owner"
        result = sanitize_archive_command(cmd)
        assert result == cmd

    def test_includes_size_check(self):
        result = sanitize_archive_command("tar xzf data.tar.gz")
        assert "du -sk" in result
        assert "exceeds" in result


class TestSanitizeUnzip:
    def test_injects_overwrite_flag(self):
        result = sanitize_archive_command("unzip archive.zip")
        assert "-o" in result

    def test_includes_size_check(self):
        result = sanitize_archive_command("unzip archive.zip")
        assert "du -sk" in result

    def test_skips_already_has_overwrite(self):
        result = sanitize_archive_command("unzip -o archive.zip")
        assert result.count("-o") >= 1


class TestPassthrough:
    def test_normal_command_unchanged(self):
        cmd = "ls -la"
        assert sanitize_archive_command(cmd) == cmd

    def test_python_command_unchanged(self):
        cmd = "python3 -c 'import tarfile'"
        assert sanitize_archive_command(cmd) == cmd

    def test_git_command_unchanged(self):
        cmd = "git clone https://github.com/example/repo.git"
        assert sanitize_archive_command(cmd) == cmd
