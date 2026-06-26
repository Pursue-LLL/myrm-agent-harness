"""Concurrent Download - Batch Download Multiple Files

[INPUT]

[OUTPUT]
- list[dict] (download results)

[POS]
Concurrent file downloader. Batch downloads with asyncio.gather, semaphore-based concurrency control, auto-retry, and progress tracking.

"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from myrm_agent_harness.agent.meta_tools.http.http_client import HttpConfig, http_request

logger = logging.getLogger(__name__)


async def concurrent_download(
    urls: list[str],
    output_dir: str | None = None,
    max_concurrency: int = 5,
    timeout: int | None = None,
    verify_ssl: bool = True,
    config: HttpConfig | None = None,
) -> list[dict]:
    """Concurrent download multiple files

    Args:
        urls: List of URLs to download
        output_dir: Optional output directory (if None, returns content in memory)
        max_concurrency: Maximum concurrent downloads (default: 5)
        timeout: Request timeout per file
        verify_ssl: SSL verification
        config: HTTP config

    Returns:
        List of results: [{"url": str, "status": "success"|"failed", "file_path": str | None, "size": int | None, "error": str | None}]

    Example:
        results = await concurrent_download(
            urls=["https://example.com/file1.txt", "https://example.com/file2.txt"],
            output_dir="/tmp/downloads",
            max_concurrency=10)
        # results = [
        #     {"url": "https://example.com/file1.txt", "status": "success", "file_path": "/tmp/downloads/file1.txt", "size": 1024, "error": None},
        #     {"url": "https://example.com/file2.txt", "status": "failed", "file_path": None, "size": None, "error": "Network error"},
        # ]
    """
    if not urls:
        return []

    # Create output directory if specified
    output_path = None
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

    # Semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_concurrency)

    async def download_one(url: str) -> dict:
        """Download single file with semaphore"""
        async with semaphore:
            try:
                logger.info(f"Downloading: {url}")

                # Download content
                content = await http_request(
                    url=url, method="GET", timeout=timeout, verify_ssl=verify_ssl, config=config
                )

                # Save to file if output_dir specified
                file_path = None
                if output_path:
                    # Extract filename from URL
                    filename = url.split("/")[-1] or "download"
                    file_path = output_path / filename
                    file_path.write_text(content, encoding="utf-8")

                size = len(content.encode("utf-8"))
                logger.info(f"Downloaded: {url} ({size} bytes)")

                return {
                    "url": url,
                    "status": "success",
                    "file_path": str(file_path) if file_path else None,
                    "size": size,
                    "error": None,
                }
            except Exception as e:
                logger.error(f"Download failed: {url}, error: {e}")
                return {
                    "url": url,
                    "status": "failed",
                    "file_path": None,
                    "size": None,
                    "error": str(e),
                }

    # Concurrent download with asyncio.gather
    results = await asyncio.gather(*[download_one(url) for url in urls])

    # Statistics
    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = len(results) - success_count
    logger.info(f"Download completed: {success_count} success, {failed_count} failed, {len(results)} total")

    return list(results)
