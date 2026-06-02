"""Tests for _media_shared security utilities."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms._media_shared.security import (
    sanitize_filename,
    validate_media_url,
)


class TestValidateMediaUrl:
    def test_valid_https_url(self) -> None:
        verdict = validate_media_url("https://example.com/video.mp4", dns_resolve=False)
        assert verdict.allowed is True

    def test_blocked_scheme(self) -> None:
        verdict = validate_media_url("ftp://example.com/video.mp4", dns_resolve=False)
        assert verdict.allowed is False

    def test_private_ip_blocked(self) -> None:
        verdict = validate_media_url("http://192.168.1.1/video.mp4", dns_resolve=False)
        assert verdict.allowed is False

    def test_localhost_blocked(self) -> None:
        verdict = validate_media_url("http://127.0.0.1/video.mp4", dns_resolve=False)
        assert verdict.allowed is False

    def test_allowed_internal_host(self) -> None:
        verdict = validate_media_url(
            "http://192.168.1.1/video.mp4",
            allowed_internal_hosts=frozenset({"192.168.1.1"}),
            dns_resolve=False,
        )
        assert verdict.allowed is True


class TestSanitizeFilename:
    def test_normal_filename(self) -> None:
        assert sanitize_filename("video.mp4") == "video.mp4"

    def test_path_traversal(self) -> None:
        result = sanitize_filename("../../etc/passwd")
        assert "/" not in result
        assert ".." not in result

    def test_unknown_extension_stripped(self) -> None:
        result = sanitize_filename("script.exe")
        assert result == "script"

    def test_known_extension_preserved(self) -> None:
        assert sanitize_filename("clip.webm") == "clip.webm"

    def test_empty_name(self) -> None:
        assert sanitize_filename("") == "media"

    def test_unicode_normalized(self) -> None:
        result = sanitize_filename("vidéo.mp4")
        assert ".mp4" in result

    def test_long_filename_truncated(self) -> None:
        result = sanitize_filename("a" * 300 + ".mp4")
        assert len(result) <= 200

    def test_special_chars_removed(self) -> None:
        result = sanitize_filename('vid<>eo|"name.mp4')
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result
