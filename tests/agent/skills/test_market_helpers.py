"""Unit tests for skill market helper functions (origin tracking, scanning, LobeHub fetch).

[INPUT]
- myrm_agent_harness.agent.skills.market.helpers (POS: shared market utilities)

[OUTPUT]
- Coverage for helpers.py branches not exercised by test_discovery_service.py:
  fetch_lobehub_as_skill (success + size cap + non-200 + bad JSON), write_origin
  exception path, read_origin missing/corrupt file, scan_all_text_files
  binary-skip and decode-failure branches.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.market.helpers import (
    fetch_lobehub_as_skill,
    read_origin,
    scan_all_text_files,
    write_origin,
)
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


class TestScanAllTextFiles:
    def test_binary_and_non_scannable_files_skipped(self) -> None:
        files = {
            "SKILL.md": b"# hello",
            "logo.png": b"\x89PNG\r\n\x1a\nbinary",
            "data.bin": b"\x00\x01\x02",
            "nested/note.txt": b"plain text",
        }
        result = scan_all_text_files("demo", files)
        assert result.is_clean
        assert result.findings == []

    def test_decode_failure_file_skipped(self) -> None:
        files = {
            "SKILL.md": b"# ok",
            "weird.py": b"\xff\xfe\x00\x01\x02",
        }
        result = scan_all_text_files("demo", files)
        assert result.is_clean

    def test_non_bytes_content_decode_error_skipped(self) -> None:
        # Defensive branch: a non-bytes value whose .decode() raises is skipped
        # instead of crashing the whole scan.
        files = {
            "SKILL.md": b"# ok",
            "odd.py": "not-bytes",  # type: ignore[arg-type]
        }
        result = scan_all_text_files("demo", files)
        assert result.is_clean


class TestWriteReadOrigin:
    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        write_origin(tmp_path, source="github", skill_id="local::abc")
        origin = read_origin(tmp_path)
        assert origin["source"] == "github"
        assert origin["skill_id"] == "local::abc"
        assert "installed_at" in origin

    def test_write_origin_io_error_is_silently_ignored(self, tmp_path: Path) -> None:
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        (blocked / "origin.json").write_text("occupied", encoding="utf-8")
        # Make origin.json a directory so write_text raises IsADirectoryError.
        origin_file = blocked / "origin.json"
        origin_file.unlink()
        origin_file.mkdir()
        write_origin(blocked, source="github", skill_id="x")  # must not raise
        assert (blocked / "origin.json").is_dir()

    def test_read_origin_missing_returns_empty(self, tmp_path: Path) -> None:
        assert read_origin(tmp_path) == {}

    def test_read_origin_corrupt_json_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "origin.json").write_text("{not-valid-json", encoding="utf-8")
        assert read_origin(tmp_path) == {}


class TestFetchLobehubAsSkill:
    def _detail(self) -> SkillSearchResult:
        return SkillSearchResult(
            id="lobe::demo",
            name="demo-agent",
            description="Demo agent",
            source="lobehub",
            author="lobehub",
            install_url="https://example.com/agent.json",
            install_method="direct",
            version="1.0.0",
        )

    def test_success_converts_json_to_skill_md(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "meta": {"title": "Demo Agent", "description": "A demo", "tags": ["t1", "t2"]},
            "config": {"systemRole": "You are helpful."},
        }
        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=resp),
        ):
            files = asyncio.run(fetch_lobehub_as_skill(self._detail()))
        content = files["SKILL.md"].decode("utf-8")
        assert "name: Demo Agent" in content
        assert "description: A demo" in content
        assert "tags: [t1, t2]" in content
        assert "You are helpful." in content

    def test_non_200_raises(self) -> None:
        resp = MagicMock()
        resp.status_code = 404
        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=resp),
        ):
            with pytest.raises(ValueError, match="fetch failed: HTTP 404"):
                asyncio.run(fetch_lobehub_as_skill(self._detail()))

    def test_content_too_large_raises(self) -> None:
        from myrm_agent_harness.core.security.http.secure_fetch import (
            ContentTooLargeError,
        )

        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(side_effect=ContentTooLargeError("too big")),
        ):
            with pytest.raises(ValueError, match="too large"):
                asyncio.run(fetch_lobehub_as_skill(self._detail()))

    def test_invalid_json_root_raises(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = ["not", "a", "dict"]
        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=resp),
        ):
            with pytest.raises(ValueError, match="not a valid JSON object"):
                asyncio.run(fetch_lobehub_as_skill(self._detail()))

    def test_meta_not_dict_falls_back_to_root(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "meta": "not-a-dict",
            "config": {"systemRole": "Fallback role."},
        }
        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=resp),
        ):
            files = asyncio.run(fetch_lobehub_as_skill(self._detail()))
        content = files["SKILL.md"].decode("utf-8")
        assert "Fallback role." in content

    def test_non_dict_meta_falls_back_to_root(self) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"meta": ["not-a-dict"]}
        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=resp),
        ):
            files = asyncio.run(fetch_lobehub_as_skill(self._detail()))
        content = files["SKILL.md"].decode("utf-8")
        assert "name: demo-agent" in content
