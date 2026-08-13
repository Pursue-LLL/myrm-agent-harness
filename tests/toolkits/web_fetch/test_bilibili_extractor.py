"""Tests for the Bilibili subtitle extractor (stdlib-only fast-path)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor import (
    _api_request,
    _build_opener,
    _extract_bvid,
    _fetch_subtitle,
    _fetch_video_metadata,
    _format_timestamp,
    extract_bilibili_subtitle,
    is_bilibili_url,
)

BVID = "BV1xx411c7mD"
BILIBILI_URL = f"https://www.bilibili.com/video/{BVID}"

_VIEW_OK = {
    "code": 0,
    "data": {
        "title": "Demo Video",
        "owner": {"name": "Alice"},
        "cid": 1234,
        "duration": 3661,
    },
}

_PLAYER_OK = {
    "code": 0,
    "data": {
        "subtitle": {
            "subtitles": [
                {"subtitle_url": "//aisubtitle.hdslb.com/abc.json"},
            ]
        }
    },
}

_SUBTITLE_BODY = [
    {"from": 0.0, "content": "hello"},
    {"from": 65.0, "content": "world"},
]


class TestUrlDetection:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.bilibili.com/video/BV1xx411c7mD", True),
            ("https://m.bilibili.com/video/BV1xx411c7mD", True),
            ("https://www.bilibili.com/video/av170001", True),
            ("https://b23.tv/abc123", True),
            ("https://www.bilibili.com/bangumi/play/ep123456", False),
            ("https://example.com/video/BV1xx411c7mD", False),
        ],
    )
    def test_is_bilibili_url(self, url: str, expected: bool) -> None:
        assert is_bilibili_url(url) is expected

    @pytest.mark.parametrize(
        "url,expected",
        [
            (BILIBILI_URL, BVID),
            ("https://www.bilibili.com/video/av170001", None),
            ("https://example.com/video/BV1xx411c7mD", None),
        ],
    )
    def test_extract_bvid(self, url: str, expected: str | None) -> None:
        assert _extract_bvid(url) == expected

    def test_format_timestamp(self) -> None:
        assert _format_timestamp(3661.9) == "1:01:01"
        assert _format_timestamp(65) == "01:05"
        assert _format_timestamp(0) == "00:00"


class TestOpenersAndApi:
    def test_build_opener_without_proxy(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor.urllib.request.build_opener"
        ) as bo:
            _build_opener(None)
            bo.assert_called_once_with()

    def test_build_opener_with_proxy(self) -> None:
        proxy = SimpleNamespace(
            get_next=lambda: SimpleNamespace(to_url=lambda: "http://127.0.0.1:8888")
        )
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor.urllib.request.build_opener"
        ) as bo:
            _build_opener(proxy)  # type: ignore[arg-type]
            assert bo.call_count == 1
            handler = bo.call_args[0][0]
            assert isinstance(handler, type(handler))

    def test_api_request_with_cookies(self) -> None:
        opener = MagicMock()
        resp = MagicMock()
        resp.read.return_value = b'{"code": 0}'
        opener.open.return_value.__enter__.return_value = resp

        data = _api_request("https://api.example.com/x", opener, cookies={"SESSDATA": "abc"})  # type: ignore[arg-type]

        assert data == {"code": 0}
        request: MagicMock = opener.open.call_args[0][0]
        assert "SESSDATA=abc" in request.headers["Cookie"]


class TestFetchVideoMetadata:
    def test_success(self) -> None:
        opener = MagicMock()
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._api_request",
            return_value=_VIEW_OK,
        ):
            result = self._run(_fetch_video_metadata(BVID, opener))  # type: ignore[arg-type]

        assert result is not None
        assert result["title"] == "Demo Video"
        assert result["author_name"] == "Alice"
        assert result["cid"] == 1234
        assert result["duration"] == 3661

    def test_nonzero_code(self) -> None:
        opener = MagicMock()
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._api_request",
            return_value={"code": -404, "message": "not found"},
        ):
            result = self._run(_fetch_video_metadata(BVID, opener))  # type: ignore[arg-type]

        assert result is None

    def test_exception(self) -> None:
        opener = MagicMock()
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._api_request",
            side_effect=OSError("network"),
        ):
            result = self._run(_fetch_video_metadata(BVID, opener))  # type: ignore[arg-type]

        assert result is None

    @staticmethod
    def _run(coro):
        import asyncio

        return asyncio.run(coro)


class TestFetchSubtitle:
    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    def test_success_with_relative_subtitle_url(self) -> None:
        opener = MagicMock()
        calls = {"n": 0}
        api_calls = [_PLAYER_OK, {"body": _SUBTITLE_BODY}]

        def fake_api(url, opener, cookies=None):
            data = api_calls[calls["n"]]
            calls["n"] += 1
            return data

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._api_request",
            side_effect=fake_api,
        ):
            result = self._run(_fetch_subtitle(BVID, 1234, opener))  # type: ignore[arg-type]

        assert result == _SUBTITLE_BODY

    def test_player_code_nonzero(self) -> None:
        opener = MagicMock()
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._api_request",
            return_value={"code": -404},
        ):
            result = self._run(_fetch_subtitle(BVID, 1234, opener))  # type: ignore[arg-type]

        assert result is None

    def test_no_subtitle_list(self) -> None:
        opener = MagicMock()
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._api_request",
            return_value={"code": 0, "data": {"subtitle": {"subtitles": []}}},
        ):
            result = self._run(_fetch_subtitle(BVID, 1234, opener))  # type: ignore[arg-type]

        assert result is None

    def test_empty_subtitle_url(self) -> None:
        opener = MagicMock()
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._api_request",
            return_value={
                "code": 0,
                "data": {"subtitle": {"subtitles": [{"subtitle_url": ""}]}},
            },
        ):
            result = self._run(_fetch_subtitle(BVID, 1234, opener))  # type: ignore[arg-type]

        assert result is None

    def test_empty_body(self) -> None:
        opener = MagicMock()
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._api_request",
            return_value={
                "code": 0,
                "data": {"subtitle": {"subtitles": [{"subtitle_url": "//x.json"}]}},
                "body": [],
            },
        ):
            result = self._run(_fetch_subtitle(BVID, 1234, opener))  # type: ignore[arg-type]

        assert result is None

    def test_exception(self) -> None:
        opener = MagicMock()
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._api_request",
            side_effect=OSError("network"),
        ):
            result = self._run(_fetch_subtitle(BVID, 1234, opener))  # type: ignore[arg-type]

        assert result is None


class TestExtractSubtitle:
    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    def test_bad_url_returns_none(self) -> None:
        assert self._run(extract_bilibili_subtitle("https://example.com/foo")) is None

    def test_metadata_missing_returns_none(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._fetch_video_metadata",
            new=AsyncMock(return_value=None),
        ):
            assert self._run(extract_bilibili_subtitle(BILIBILI_URL)) is None

    def test_zero_cid_returns_none(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._fetch_video_metadata",
            new=AsyncMock(
                return_value={"cid": 0, "duration": 0, "title": "", "author_name": ""}
            ),
        ):
            assert self._run(extract_bilibili_subtitle(BILIBILI_URL)) is None

    def test_no_subtitle_returns_none(self) -> None:
        with (
            patch(
                "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._fetch_video_metadata",
                new=AsyncMock(
                    return_value={
                        "cid": 1234,
                        "duration": 60,
                        "title": "T",
                        "author_name": "A",
                    }
                ),
            ),
            patch(
                "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._fetch_subtitle",
                new=AsyncMock(return_value=None),
            ),
        ):
            assert self._run(extract_bilibili_subtitle(BILIBILI_URL)) is None

    def test_full_success(self) -> None:
        metadata = {
            "cid": 1234,
            "duration": 3661,
            "title": "Demo",
            "author_name": "Alice",
            "bvid": BVID,
        }
        segments = [
            {"from": 0.0, "content": "hello"},
            {"from": 65.0, "content": "world"},
        ]
        with (
            patch(
                "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._fetch_video_metadata",
                new=AsyncMock(return_value=metadata),
            ),
            patch(
                "myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor._fetch_subtitle",
                new=AsyncMock(return_value=segments),
            ),
        ):
            doc = self._run(extract_bilibili_subtitle(BILIBILI_URL))

        assert isinstance(doc, Document)
        assert doc.page_content == "00:00 hello\n01:05 world"
        assert doc.metadata["title"] == "Demo"
        assert doc.metadata["author_name"] == "Alice"
        assert doc.metadata["duration"] == "1:01:01"
        assert doc.metadata["segment_count"] == 2
        assert doc.metadata["source_type"] == "bilibili_subtitle"
