"""Download manager — file download detection, processing, and PDF auto-download.

[INPUT]
- patchright.async_api::Page, Download (POS: Patchright page and download objects)

[OUTPUT]
- DownloadManager: file download manager
- DownloadConfig: download configuration
- DownloadResult: immutable download result

[POS]
Browser file download manager. Single responsibility: listen for, process, and record file downloads.
Integrated into BrowserSession as an optional component.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Download, Page

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        "pdf",
        "csv",
        "xlsx",
        "xls",
        "doc",
        "docx",
        "ppt",
        "pptx",
        "txt",
        "json",
        "xml",
        "zip",
        "gz",
        "tar",
        "rar",
        "7z",
        "md",
        "html",
        "htm",
        "rtf",
        "odt",
        "ods",
        "odp",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "svg",
        "webp",
        "mp3",
        "mp4",
        "wav",
        "avi",
        "mkv",
        "webm",
        "py",
        "js",
        "ts",
        "java",
        "cpp",
        "c",
        "rs",
        "go",
        "yaml",
        "yml",
        "toml",
        "ini",
        "cfg",
        "conf",
        "log",
        "sql",
        "db",
        "sqlite",
        "bak",
    }
)

_FILENAME_SANITIZE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class DownloadConfig:
    """Download configuration."""

    downloads_dir: Path = field(default_factory=lambda: Path.home() / ".myrm" / "downloads")
    auto_download_pdf: bool = True
    max_file_size_mb: int = 100
    download_timeout_s: float = 60.0
    max_concurrent_downloads: int = 3
    allowed_extensions: frozenset[str] = _DEFAULT_ALLOWED_EXTENSIONS


@dataclass(frozen=True)
class DownloadResult:
    """Immutable download result."""

    url: str
    path: str
    file_name: str
    file_size: int
    file_type: str | None = None
    mime_type: str | None = None
    auto_download: bool = False


class DownloadManager:
    """File download manager with PDF auto-detection.

    Monitors page download events, processes files with safety checks,
    and provides PDF auto-detection and download capabilities.
    """

    def __init__(self, config: DownloadConfig | None = None) -> None:
        self._config = config or DownloadConfig()
        self._downloads: list[DownloadResult] = []
        self._downloaded_urls: set[str] = set()
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_downloads)
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._attached_page_ids: set[int] = set()

        self._config.downloads_dir.mkdir(parents=True, exist_ok=True)

    def attach(self, page: Page) -> None:
        """Attach download listener to a page (idempotent per page instance)."""
        page_id = id(page)
        if page_id in self._attached_page_ids:
            return
        self._attached_page_ids.add(page_id)
        page.on("download", lambda download: self._on_download(download))

    @property
    def downloads(self) -> list[DownloadResult]:
        """Get all download results."""
        return list(self._downloads)

    @property
    def last_download(self) -> DownloadResult | None:
        """Get the most recent download result."""
        return self._downloads[-1] if self._downloads else None

    async def download_url(self, page: Page, url: str, timeout: float | None = None) -> DownloadResult | None:
        """Actively download a file from a URL.

        Args:
            page: Page to initiate download from
            url: URL to download
            timeout: Download timeout in seconds (defaults to config)

        Returns:
            DownloadResult if successful, None otherwise
        """
        if url in self._downloaded_urls:
            for result in reversed(self._downloads):
                if result.url == url and Path(result.path).exists():
                    return result

        effective_timeout = (timeout or self._config.download_timeout_s) * 1000

        try:
            async with self._semaphore:
                async with page.expect_download(timeout=effective_timeout) as download_info:
                    await page.evaluate(f"() => window.location.href = {url!r}")

                download = await download_info.value
                return await self._process_download(download, auto=False)
        except Exception as e:
            logger.warning("Failed to download URL %s: %s", url[:80], e)
            return None

    async def check_and_download_pdf(self, page: Page) -> DownloadResult | None:
        """Check if current page is a PDF and auto-download it.

        Args:
            page: Current page to check

        Returns:
            DownloadResult if PDF was downloaded, None otherwise
        """
        if not self._config.auto_download_pdf:
            return None

        url = page.url
        if not url or not url.startswith("http"):
            return None

        if url in self._downloaded_urls:
            return None

        if not self._is_pdf_url(url):
            is_pdf = await self._check_pdf_viewer(page)
            if not is_pdf:
                return None

        try:
            async with self._semaphore:
                async with page.expect_download(timeout=self._config.download_timeout_s * 1000) as download_info:
                    await page.evaluate("() => window.print()")

                download = await download_info.value
                return await self._process_download(download, auto=True)
        except Exception:
            return await self._download_pdf_via_fetch(page, url)

    async def cleanup(self) -> None:
        """Cancel pending tasks and clean up resources."""
        for task in list(self._pending_tasks):
            if not task.done():
                task.cancel()
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        self._pending_tasks.clear()

    def _on_download(self, download: Download) -> None:
        """Handle download event from page (sync callback → async task)."""
        task = asyncio.create_task(self._handle_download_async(download))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _handle_download_async(self, download: Download) -> None:
        """Process a download event asynchronously."""
        try:
            async with self._semaphore:
                await self._process_download(download, auto=False)
        except Exception as e:
            logger.warning("Download handler error: %s", e)

    async def _process_download(self, download: Download, *, auto: bool) -> DownloadResult | None:
        """Process a Patchright Download object.

        Args:
            download: Patchright Download object
            auto: Whether this is an auto-download (PDF)

        Returns:
            DownloadResult if successful, None otherwise
        """
        url = download.url
        suggested = download.suggested_filename

        sanitized = self._sanitize_filename(suggested)
        ext = Path(sanitized).suffix.lower().lstrip(".")
        if ext and ext not in self._config.allowed_extensions:
            logger.info("Skipping download with disallowed extension: .%s", ext)
            with contextlib.suppress(Exception):
                await download.cancel()
            return None

        unique_name = self._generate_unique_filename(sanitized)
        target_path = self._config.downloads_dir / unique_name

        try:
            await asyncio.wait_for(
                download.save_as(str(target_path)),
                timeout=self._config.download_timeout_s,
            )
        except TimeoutError:
            logger.warning("Download timed out: %s", url[:80])
            return None
        except Exception as e:
            failure = await download.failure()
            logger.warning("Download failed for %s: %s (failure=%s)", url[:80], e, failure)
            return None

        if not target_path.exists():
            logger.warning("Download file not found after save: %s", target_path)
            return None

        file_size = target_path.stat().st_size
        max_bytes = self._config.max_file_size_mb * 1024 * 1024
        if file_size > max_bytes:
            logger.warning(
                "Downloaded file exceeds size limit (%d MB > %d MB), removing: %s",
                file_size // (1024 * 1024),
                self._config.max_file_size_mb,
                unique_name,
            )
            target_path.unlink(missing_ok=True)
            return None

        result = DownloadResult(
            url=url,
            path=str(target_path),
            file_name=unique_name,
            file_size=file_size,
            file_type=ext or None,
            auto_download=auto,
        )
        self._downloads.append(result)
        self._downloaded_urls.add(url)

        logger.info("Downloaded: %s (%d bytes) → %s", unique_name, file_size, target_path)
        return result

    async def _download_pdf_via_fetch(self, page: Page, url: str) -> DownloadResult | None:
        """Fallback: download PDF via JS fetch (uses browser cache)."""
        try:
            filename = self._extract_filename_from_url(url, default_ext=".pdf")
            sanitized = self._sanitize_filename(filename)
            unique_name = self._generate_unique_filename(sanitized)
            target_path = self._config.downloads_dir / unique_name

            escaped_url = url.replace("\\", "\\\\").replace("`", "\\`")
            js = f"""
            (async () => {{
                const r = await fetch(`{escaped_url}`, {{cache: 'force-cache'}});
                if (!r.ok) throw new Error(`HTTP ${{r.status}}`);
                const buf = await r.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }})()
            """
            data = await asyncio.wait_for(
                page.evaluate(js),
                timeout=self._config.download_timeout_s,
            )

            if not data:
                return None

            target_path.write_bytes(bytes(data))
            file_size = target_path.stat().st_size

            max_bytes = self._config.max_file_size_mb * 1024 * 1024
            if file_size > max_bytes:
                logger.warning(
                    "PDF fetch exceeds size limit (%d MB > %d MB), removing: %s",
                    file_size // (1024 * 1024),
                    self._config.max_file_size_mb,
                    unique_name,
                )
                target_path.unlink(missing_ok=True)
                return None

            result = DownloadResult(
                url=url,
                path=str(target_path),
                file_name=unique_name,
                file_size=file_size,
                file_type="pdf",
                mime_type="application/pdf",
                auto_download=True,
            )
            self._downloads.append(result)
            self._downloaded_urls.add(url)
            logger.info("PDF fetched: %s (%d bytes)", unique_name, file_size)
            return result
        except Exception as e:
            logger.warning("PDF fetch fallback failed for %s: %s", url[:80], e)
            return None

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize filename to prevent directory traversal and invalid characters."""
        name = Path(name).name
        name = _FILENAME_SANITIZE_RE.sub("_", name)
        return name.strip(". ") or "download"

    def _generate_unique_filename(self, name: str) -> str:
        """Generate unique filename using (1), (2), ... pattern."""
        if not (self._config.downloads_dir / name).exists():
            return name
        base, ext = os.path.splitext(name)
        counter = 1
        while (self._config.downloads_dir / f"{base} ({counter}){ext}").exists():
            counter += 1
        return f"{base} ({counter}){ext}"

    @staticmethod
    def _is_pdf_url(url: str) -> bool:
        """Check if URL indicates a PDF file."""
        url_lower = url.lower()
        path_part = url_lower.split("?")[0]
        if path_part.endswith(".pdf"):
            return True
        pdf_params = (
            "content-type=application/pdf",
            "content-type=application%2fpdf",
            "mimetype=application/pdf",
            "type=application/pdf",
        )
        return any(p in url_lower for p in pdf_params)

    @staticmethod
    async def _check_pdf_viewer(page: Page) -> bool:
        """Check if current page is Chrome's PDF viewer."""
        try:
            url = page.url
            if "chrome-extension://" in url.lower() and "pdf" in url.lower():
                return True
            if url.lower().startswith("chrome://") and "pdf" in url.lower():
                return True
            result = await asyncio.wait_for(
                page.evaluate(
                    '() => !!document.querySelector(\'embed[type="application/pdf"], '
                    'embed[type="application/x-google-chrome-pdf"]\')'
                ),
                timeout=3.0,
            )
            return bool(result)
        except Exception:
            return False

    @staticmethod
    def _extract_filename_from_url(url: str, *, default_ext: str = "") -> str:
        """Extract filename from URL."""
        path = url.split("?")[0].split("#")[0]
        name = os.path.basename(path)
        if not name or "." not in name:
            return f"document{default_ext}" if default_ext else "download"
        return name
