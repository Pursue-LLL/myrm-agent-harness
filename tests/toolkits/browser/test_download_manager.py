"""Unit tests for DownloadManager — full coverage with mocks."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.session.download_manager import (
    _DEFAULT_ALLOWED_EXTENSIONS,
    DownloadConfig,
    DownloadManager,
    DownloadResult,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tmp_downloads(tmp_path: Path) -> Path:
    dl_dir = tmp_path / "downloads"
    dl_dir.mkdir()
    return dl_dir


@pytest.fixture
def config(tmp_downloads: Path) -> DownloadConfig:
    return DownloadConfig(
        downloads_dir=tmp_downloads,
        auto_download_pdf=True,
        max_file_size_mb=1,
        download_timeout_s=5.0,
        max_concurrent_downloads=2,
    )


@pytest.fixture
def manager(config: DownloadConfig) -> DownloadManager:
    return DownloadManager(config)


def _make_download_mock(
    url: str = "https://example.com/file.pdf",
    suggested_filename: str = "file.pdf",
    *,
    save_content: bytes = b"%PDF-fake-content",
    failure_msg: str | None = None,
) -> MagicMock:
    """Create a mock Patchright Download object."""
    dl = MagicMock()
    dl.url = url
    dl.suggested_filename = suggested_filename
    dl.failure = AsyncMock(return_value=failure_msg)
    dl.cancel = AsyncMock()

    async def _save_as(path: str) -> None:
        if failure_msg:
            raise RuntimeError(failure_msg)
        Path(path).write_bytes(save_content)

    dl.save_as = AsyncMock(side_effect=_save_as)
    return dl


def _make_page_mock() -> MagicMock:
    page = MagicMock()
    page.url = "https://example.com/report.pdf"
    page.evaluate = AsyncMock(return_value=None)
    page.on = MagicMock()
    return page


# =============================================================================
# DownloadConfig tests
# =============================================================================


class TestDownloadConfig:
    def test_default_config(self) -> None:
        cfg = DownloadConfig()
        assert cfg.auto_download_pdf is True
        assert cfg.max_file_size_mb == 100
        assert cfg.download_timeout_s == 60.0
        assert cfg.max_concurrent_downloads == 3
        assert cfg.allowed_extensions is _DEFAULT_ALLOWED_EXTENSIONS

    def test_custom_config(self, tmp_downloads: Path) -> None:
        cfg = DownloadConfig(
            downloads_dir=tmp_downloads,
            max_file_size_mb=50,
            allowed_extensions=frozenset({"pdf", "csv"}),
        )
        assert cfg.downloads_dir == tmp_downloads
        assert cfg.max_file_size_mb == 50
        assert cfg.allowed_extensions == frozenset({"pdf", "csv"})

    def test_config_frozen(self) -> None:
        cfg = DownloadConfig()
        with pytest.raises(AttributeError):
            cfg.max_file_size_mb = 999  # type: ignore[misc]


# =============================================================================
# DownloadResult tests
# =============================================================================


class TestDownloadResult:
    def test_result_frozen(self) -> None:
        result = DownloadResult(
            url="https://x.com/f.pdf",
            path="/tmp/f.pdf",
            file_name="f.pdf",
            file_size=1024,
            file_type="pdf",
        )
        assert result.url == "https://x.com/f.pdf"
        assert result.auto_download is False
        with pytest.raises(AttributeError):
            result.file_name = "other"  # type: ignore[misc]

    def test_result_auto_download(self) -> None:
        result = DownloadResult(
            url="u",
            path="p",
            file_name="f",
            file_size=0,
            auto_download=True,
        )
        assert result.auto_download is True


# =============================================================================
# DownloadManager core tests
# =============================================================================


class TestDownloadManagerInit:
    def test_init_creates_directory(self, tmp_path: Path) -> None:
        dl_dir = tmp_path / "new_dir" / "nested"
        cfg = DownloadConfig(downloads_dir=dl_dir)
        DownloadManager(cfg)
        assert dl_dir.exists()

    def test_init_default_config(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg = DownloadConfig(downloads_dir=Path(d))
            dm = DownloadManager(cfg)
            assert dm.downloads == []
            assert dm.last_download is None


class TestDownloadManagerAttach:
    def test_attach_registers_listener(self, manager: DownloadManager) -> None:
        page = _make_page_mock()
        manager.attach(page)
        page.on.assert_called_once()
        assert page.on.call_args[0][0] == "download"

    def test_attach_idempotent_same_page(self, manager: DownloadManager) -> None:
        """Same page object attached twice should only register listener once."""
        page = _make_page_mock()
        manager.attach(page)
        manager.attach(page)
        page.on.assert_called_once()

    def test_attach_different_pages(self, manager: DownloadManager) -> None:
        """Different pages should each get their own listener."""
        page1 = _make_page_mock()
        page2 = _make_page_mock()
        manager.attach(page1)
        manager.attach(page2)
        assert page1.on.call_count == 1
        assert page2.on.call_count == 1


class TestDownloadManagerProcessDownload:
    @pytest.mark.asyncio
    async def test_successful_download(self, manager: DownloadManager) -> None:
        dl = _make_download_mock()
        result = await manager._process_download(dl, auto=False)

        assert result is not None
        assert result.file_name == "file.pdf"
        assert result.file_type == "pdf"
        assert result.auto_download is False
        assert Path(result.path).exists()
        assert manager.downloads == [result]
        assert manager.last_download is result

    @pytest.mark.asyncio
    async def test_auto_download_flag(self, manager: DownloadManager) -> None:
        dl = _make_download_mock()
        result = await manager._process_download(dl, auto=True)
        assert result is not None
        assert result.auto_download is True

    @pytest.mark.asyncio
    async def test_disallowed_extension_rejected(self, tmp_downloads: Path) -> None:
        cfg = DownloadConfig(
            downloads_dir=tmp_downloads,
            allowed_extensions=frozenset({"pdf"}),
        )
        dm = DownloadManager(cfg)
        dl = _make_download_mock(
            url="https://x.com/malware.exe",
            suggested_filename="malware.exe",
        )
        result = await dm._process_download(dl, auto=False)
        assert result is None
        dl.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_file_size_exceeded(self, tmp_downloads: Path) -> None:
        cfg = DownloadConfig(
            downloads_dir=tmp_downloads,
            max_file_size_mb=0,  # 0 MB limit — any file exceeds
        )
        dm = DownloadManager(cfg)
        dl = _make_download_mock(save_content=b"some content")
        result = await dm._process_download(dl, auto=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_save_failure(self, manager: DownloadManager) -> None:
        dl = _make_download_mock(failure_msg="network error")
        result = await manager._process_download(dl, auto=False)
        assert result is None
        assert manager.downloads == []

    @pytest.mark.asyncio
    async def test_url_deduplication(self, manager: DownloadManager) -> None:
        dl1 = _make_download_mock()
        dl2 = _make_download_mock()

        r1 = await manager._process_download(dl1, auto=False)
        r2 = await manager._process_download(dl2, auto=False)

        assert r1 is not None
        assert r2 is not None
        assert r1.file_name == "file.pdf"
        assert r2.file_name == "file (1).pdf"
        assert len(manager.downloads) == 2


class TestDownloadManagerSanitize:
    @pytest.mark.parametrize(
        ("input_name", "expected"),
        [
            ("normal.pdf", "normal.pdf"),
            ("../../etc/passwd", "passwd"),
            ("file<name>.txt", "file_name_.txt"),
            (" . . ", "download"),
            ("file:with:colons.doc", "file_with_colons.doc"),
        ],
    )
    def test_sanitize_filename(self, input_name: str, expected: str) -> None:
        assert DownloadManager._sanitize_filename(input_name) == expected


class TestDownloadManagerUniqueFilename:
    def test_no_conflict(self, manager: DownloadManager) -> None:
        assert manager._generate_unique_filename("report.pdf") == "report.pdf"

    def test_with_conflict(self, manager: DownloadManager, tmp_downloads: Path) -> None:
        (tmp_downloads / "report.pdf").touch()
        assert manager._generate_unique_filename("report.pdf") == "report (1).pdf"

    def test_multiple_conflicts(self, manager: DownloadManager, tmp_downloads: Path) -> None:
        (tmp_downloads / "report.pdf").touch()
        (tmp_downloads / "report (1).pdf").touch()
        (tmp_downloads / "report (2).pdf").touch()
        assert manager._generate_unique_filename("report.pdf") == "report (3).pdf"


class TestDownloadManagerPdfDetection:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://x.com/file.pdf", True),
            ("https://x.com/file.PDF", True),
            ("https://x.com/file.pdf?v=1", True),
            ("https://x.com/page?content-type=application/pdf", True),
            ("https://x.com/page?content-type=application%2fpdf", True),
            ("https://x.com/file.txt", False),
            ("https://x.com/page", False),
        ],
    )
    def test_is_pdf_url(self, url: str, expected: bool) -> None:
        assert DownloadManager._is_pdf_url(url) is expected

    @pytest.mark.asyncio
    async def test_check_pdf_viewer_embed(self) -> None:
        page = _make_page_mock()
        page.url = "https://x.com/doc"
        page.evaluate = AsyncMock(return_value=True)
        assert await DownloadManager._check_pdf_viewer(page) is True

    @pytest.mark.asyncio
    async def test_check_pdf_viewer_chrome_extension(self) -> None:
        page = _make_page_mock()
        page.url = "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html?pdf=1"
        assert await DownloadManager._check_pdf_viewer(page) is True

    @pytest.mark.asyncio
    async def test_check_pdf_viewer_none(self) -> None:
        page = _make_page_mock()
        page.url = "https://example.com"
        page.evaluate = AsyncMock(return_value=False)
        assert await DownloadManager._check_pdf_viewer(page) is False

    @pytest.mark.asyncio
    async def test_check_pdf_viewer_error(self) -> None:
        page = _make_page_mock()
        page.url = "https://example.com"
        page.evaluate = AsyncMock(side_effect=Exception("timeout"))
        assert await DownloadManager._check_pdf_viewer(page) is False


class TestExtractFilenameFromUrl:
    @pytest.mark.parametrize(
        ("url", "default_ext", "expected"),
        [
            ("https://x.com/file.pdf", "", "file.pdf"),
            ("https://x.com/file.pdf?v=2#sec", "", "file.pdf"),
            ("https://x.com/", ".pdf", "document.pdf"),
            ("https://x.com/noext", "", "download"),
            ("https://x.com/noext", ".pdf", "document.pdf"),
        ],
    )
    def test_extract(self, url: str, default_ext: str, expected: str) -> None:
        assert DownloadManager._extract_filename_from_url(url, default_ext=default_ext) == expected


# =============================================================================
# download_url tests
# =============================================================================


class TestDownloadUrl:
    @pytest.mark.asyncio
    async def test_download_url_success(self, manager: DownloadManager) -> None:
        page = _make_page_mock()
        download_mock = _make_download_mock(url="https://x.com/data.csv", suggested_filename="data.csv")

        class _DownloadInfoValue:
            """Mimic Playwright's EventInfoType that holds an awaitable .value."""

            def __init__(self, dl: MagicMock) -> None:
                self._dl = dl

            def __await__(self):
                return self._resolve().__await__()

            async def _resolve(self) -> MagicMock:
                return self._dl

        class _FakeExpectDownload:
            def __init__(self, **_kw: object) -> None:
                self.value = _DownloadInfoValue(download_mock)

            async def __aenter__(self) -> _FakeExpectDownload:
                return self

            async def __aexit__(self, *_a: object) -> bool:
                return False

        page.expect_download = _FakeExpectDownload

        result = await manager.download_url(page, "https://x.com/data.csv")
        assert result is not None
        assert result.file_name == "data.csv"

    @pytest.mark.asyncio
    async def test_download_url_dedup(self, manager: DownloadManager) -> None:
        dl = _make_download_mock(url="https://x.com/f.pdf")
        await manager._process_download(dl, auto=False)

        page = _make_page_mock()
        result = await manager.download_url(page, "https://x.com/f.pdf")
        assert result is not None
        assert result.url == "https://x.com/f.pdf"

    @pytest.mark.asyncio
    async def test_download_url_failure(self, manager: DownloadManager) -> None:
        page = _make_page_mock()
        page.expect_download = MagicMock(side_effect=Exception("error"))

        result = await manager.download_url(page, "https://x.com/broken")
        assert result is None


# =============================================================================
# check_and_download_pdf tests
# =============================================================================


class TestCheckAndDownloadPdf:
    @pytest.mark.asyncio
    async def test_disabled(self, tmp_downloads: Path) -> None:
        cfg = DownloadConfig(downloads_dir=tmp_downloads, auto_download_pdf=False)
        dm = DownloadManager(cfg)
        page = _make_page_mock()
        assert await dm.check_and_download_pdf(page) is None

    @pytest.mark.asyncio
    async def test_non_http_url(self, manager: DownloadManager) -> None:
        page = _make_page_mock()
        page.url = "about:blank"
        assert await manager.check_and_download_pdf(page) is None

    @pytest.mark.asyncio
    async def test_already_downloaded(self, manager: DownloadManager) -> None:
        dl = _make_download_mock(url="https://x.com/report.pdf")
        await manager._process_download(dl, auto=True)

        page = _make_page_mock()
        page.url = "https://x.com/report.pdf"
        assert await manager.check_and_download_pdf(page) is None

    @pytest.mark.asyncio
    async def test_not_pdf_page(self, manager: DownloadManager) -> None:
        page = _make_page_mock()
        page.url = "https://example.com/page"
        page.evaluate = AsyncMock(return_value=False)
        assert await manager.check_and_download_pdf(page) is None

    @pytest.mark.asyncio
    async def test_pdf_fallback_to_fetch(self, manager: DownloadManager, tmp_downloads: Path) -> None:
        page = _make_page_mock()
        page.url = "https://x.com/doc.pdf"

        page.expect_download = MagicMock(side_effect=Exception("no print dialog"))
        page.evaluate = AsyncMock(return_value=list(b"%PDF-1.4 fake"))

        result = await manager.check_and_download_pdf(page)
        assert result is not None
        assert result.file_type == "pdf"
        assert result.auto_download is True

    @pytest.mark.asyncio
    async def test_pdf_fetch_size_exceeded(self, tmp_downloads: Path) -> None:
        """PDF fetched via JS that exceeds max_file_size_mb should be deleted."""
        cfg = DownloadConfig(
            downloads_dir=tmp_downloads,
            max_file_size_mb=0,  # 0 MB limit
        )
        dm = DownloadManager(cfg)
        page = _make_page_mock()
        page.url = "https://x.com/huge.pdf"

        page.expect_download = MagicMock(side_effect=Exception("no print"))
        page.evaluate = AsyncMock(return_value=list(b"%PDF-big-content"))

        result = await dm.check_and_download_pdf(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_pdf_both_methods_fail(self, manager: DownloadManager) -> None:
        page = _make_page_mock()
        page.url = "https://x.com/doc.pdf"

        page.expect_download = MagicMock(side_effect=Exception("fail"))
        page.evaluate = AsyncMock(side_effect=Exception("fetch fail"))

        result = await manager.check_and_download_pdf(page)
        assert result is None


# =============================================================================
# cleanup tests
# =============================================================================


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_cancels_pending(self, manager: DownloadManager) -> None:
        task = MagicMock()
        task.done.return_value = False
        task.cancel = MagicMock()
        manager._pending_tasks.add(task)

        with patch("asyncio.gather", new_callable=AsyncMock):
            await manager.cleanup()

        task.cancel.assert_called_once()
        assert len(manager._pending_tasks) == 0

    @pytest.mark.asyncio
    async def test_cleanup_empty(self, manager: DownloadManager) -> None:
        await manager.cleanup()
        assert len(manager._pending_tasks) == 0


# =============================================================================
# _on_download (sync → async bridge) tests
# =============================================================================


class TestOnDownload:
    @pytest.mark.asyncio
    async def test_on_download_creates_task(self, manager: DownloadManager) -> None:
        dl = _make_download_mock()
        manager._on_download(dl)
        assert len(manager._pending_tasks) >= 1
        await asyncio.gather(*list(manager._pending_tasks), return_exceptions=True)
        assert len(manager.downloads) == 1

    @pytest.mark.asyncio
    async def test_on_download_error_handled(self, manager: DownloadManager) -> None:
        dl = _make_download_mock(failure_msg="fail")
        manager._on_download(dl)
        await asyncio.gather(*list(manager._pending_tasks), return_exceptions=True)
        assert len(manager.downloads) == 0


# =============================================================================
# Integration: BrowserSession download delegation
# =============================================================================


class TestBrowserSessionDownloadIntegration:
    def test_list_downloads_no_manager(self) -> None:
        from myrm_agent_harness.toolkits.browser.session import BrowserSession

        pool = MagicMock()
        session = BrowserSession(pool, "AGENT")
        assert session.list_downloads() == []

    def test_list_downloads_with_manager(self, tmp_downloads: Path) -> None:
        from myrm_agent_harness.toolkits.browser.session import BrowserSession

        pool = MagicMock()
        cfg = DownloadConfig(downloads_dir=tmp_downloads)
        session = BrowserSession(pool, "AGENT", download_config=cfg)
        assert session.list_downloads() == []
        assert session._download_manager is not None

    @pytest.mark.asyncio
    async def test_download_url_no_manager_raises(self) -> None:
        from myrm_agent_harness.toolkits.browser.session import BrowserSession

        pool = MagicMock()
        session = BrowserSession(pool, "AGENT")
        with pytest.raises(RuntimeError, match="Download support not enabled"):
            await session.download_url("https://x.com/f.pdf")

    def test_stats_includes_downloads(self, tmp_downloads: Path) -> None:
        from myrm_agent_harness.toolkits.browser.session import BrowserSession

        pool = MagicMock()
        cfg = DownloadConfig(downloads_dir=tmp_downloads)
        session = BrowserSession(pool, "AGENT", download_config=cfg)
        stats = session.stats
        assert "downloads" in stats
        assert stats["downloads"] == 0
